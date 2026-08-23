import copy
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.validate_phase2 import main as script_main
from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.cli import main as cli_main
from sedb_ral.contracts import validate_contract
from sedb_ral.errors import RALValidationError
from sedb_ral.phase2 import (
    finalize_basic_phase2,
    validate_basic_phase2,
    write_basic_phase2_receipt,
)


ROOT = Path(__file__).parents[1]
ARCHIVE = Path(r"C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip")
WRONG_HASH = json.loads(
    (ROOT / "fixtures/sedb/wrong-archive-hash.json").read_text(encoding="utf-8")
)
CTCL_INSTANT_ID = "ctcl:instant:00000000-0000-4000-8000-000000000007"
CTCL_REGISTER_RESPONSE = {
    "id": CTCL_INSTANT_ID,
    "registered": True,
    "share_url": "https://ctcl.example.test/instant/7",
}
CTCL_RETRIEVE_RESPONSE = {
    "id": CTCL_INSTANT_ID,
    "retrieved": True,
}


@pytest.fixture(scope="module")
def phase2_report():
    if not ARCHIVE.is_file():
        pytest.skip("archive_unavailable")
    return validate_basic_phase2(ROOT, ARCHIVE)


def finalize_for_test(report):
    return finalize_basic_phase2(
        report,
        ctcl_instant_id=CTCL_INSTANT_ID,
        register_response=CTCL_REGISTER_RESPONSE,
        retrieve_response=CTCL_RETRIEVE_RESPONSE,
    )


def assert_write_rejected(report, tmp_path, error_code):
    destination = tmp_path / "VALIDATION_BASIC_PHASE2.json"
    with pytest.raises(RALValidationError, match=error_code):
        write_basic_phase2_receipt(report, destination)
    assert not destination.exists()


def test_basic_phase2_gate_passes_exact_archive(phase2_report):
    assert phase2_report.passed is True
    assert phase2_report.diff_counts["contradiction"] == 0


def test_wrong_hash_fixture_proves_adoption_gate_red():
    report = validate_basic_phase2(ROOT, ARCHIVE, profile=WRONG_HASH)

    assert report.passed is False
    assert "archive_hash_mismatch" in report.error_codes


def test_receipt_records_the_exact_vertical_evidence(phase2_report):
    payload = phase2_report.as_json()

    assert payload["schema_version"] == "0.2"
    assert payload["compatibility_subject_id"] == (
        "sha256:sedb-ral-json-nfc-codepoint-v1:"
        "74449966add4d981a9df631945ce6b95399fbfa1c89d4375500cae4223bd37da"
    )
    assert payload["receipt_id"] is None
    assert phase2_report.phase1a_passed is True
    assert phase2_report.phase1bc_passed is True
    assert payload["archive"] == {
        "filename": "SEDB-v0.4B-local.zip",
        "size": 8980052,
        "sha256": "159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8",
    }
    assert payload["manifest"] == {
        "path": "MANIFEST.sha256",
        "expected_entry_count": 114,
        "observed_entry_count": 114,
        "verified": True,
    }
    assert payload["package"] == {
        "name": "sedb-local",
        "version": "0.4.0b1",
        "source_commit": "139b9952bb283b2e95f7690d76e3c5fbcdc680aa",
    }
    assert payload["mapping_profile_digest"] == (
        "sha256:sedb-ral-json-nfc-codepoint-v1:"
        "07d67d5135b97ba8a9521e3f6c33a6897e64ec65422a02cabea6cb0c398d9ef5"
    )
    assert payload["phase1"]["projection_head"] == (
        "evt_resident_registered_9e5cd5acec119d11"
    )
    assert payload["integration"] == {
        "database_integrity": "ok",
        "field_count": 8,
        "entity_count": 1,
        "cell_count": 7,
        "expected_record_count": 1,
        "exported_record_count": 1,
        "records_match": True,
        "raw_export_sha256": (
            "fc8e77dac6c15471b27dfd3e70ac533137a234ed8fa3330aa9d027d2c52e24eb"
        ),
        "normalized_export_digest": (
            "sha256:sedb-ral-json-nfc-codepoint-v1:"
            "b55c83085c8c5d55a0735c479387d28bb08b7ae630610dd4ad80b9f54dee61e2"
        ),
    }
    assert payload["differential"]["counts"] == {
        "expected_by_mapping": 0,
        "unmapped": 0,
        "contradiction": 0,
    }
    assert payload["sedb_tests"] == {
        "selected_source": "own_execution",
        "package_claim": None,
        "own_execution": {
            "passed": 189,
            "failed": 0,
            "skipped": 0,
            "fresh_execution": False,
            "inherited_from": (
                ".superpowers/sdd/2026-08-23-basic-phase-2-sedb-profile/"
                "task-5-report.md"
            ),
        },
    }
    assert payload["signature_presence"] == "not_performed"
    assert payload["ctcl"] == {
        "state": "CTCL_FINAL_PENDING",
        "instant_id": None,
        "register_response": None,
        "retrieve_response": None,
    }
    validate_contract(
        "sedb-compatibility-receipt.schema.json",
        payload,
        ROOT / "src/sedb_ral/schemas",
    )


def test_all_five_phase2_fault_controls_are_executed_and_turn_red(phase2_report):
    controls = {item.name: item.as_json() for item in phase2_report.executed_controls}

    expected_codes = {
        "archive_hash": "archive_hash_mismatch",
        "manifest": "manifest_hash_mismatch",
        "mapping_contradiction": "mapped_value_contradiction",
        "null_vs_false": "null_vs_false_contradiction",
        "no_send": "forbidden_call:socket.create_connection",
    }
    assert set(controls) == set(expected_codes)
    assert all(item["executed"] is True for item in controls.values())
    assert {
        name: item["expected_code"] for name, item in controls.items()
    } == expected_codes
    assert {
        name: item["observed_code"] for name, item in controls.items()
    } == expected_codes
    assert all(item["injected_change"] for item in controls.values())


def test_phase2_cli_routes_exact_root_and_archive_and_emits_report(
    phase2_report, monkeypatch, capsys
):
    calls = []

    def validate(root, archive):
        calls.append((root, archive))
        return phase2_report

    monkeypatch.setattr("sedb_ral.cli.validate_basic_phase2", validate)

    exit_code = cli_main(
        [
            "phase2",
            "verify",
            str(ROOT),
            "--sedb-archive",
            str(ARCHIVE),
        ]
    )

    assert exit_code == 0
    assert calls == [(ROOT, ARCHIVE)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["ctcl"]["state"] == "CTCL_FINAL_PENDING"


def test_phase2_script_routes_worktree_root_and_archive_and_emits_report(
    phase2_report, monkeypatch, capsys
):
    calls = []

    def validate(root, archive):
        calls.append((root, archive))
        return phase2_report

    monkeypatch.setattr("scripts.validate_phase2.validate_basic_phase2", validate)

    exit_code = script_main(["--sedb-archive", str(ARCHIVE)])

    assert exit_code == 0
    assert calls == [(ROOT, ARCHIVE)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["ctcl"]["state"] == "CTCL_FINAL_PENDING"


def test_ctcl_finalization_preserves_exact_register_and_retrieve_responses(
    phase2_report,
):
    finalized = finalize_basic_phase2(
        phase2_report,
        ctcl_instant_id=CTCL_INSTANT_ID,
        register_response=CTCL_REGISTER_RESPONSE,
        retrieve_response=CTCL_RETRIEVE_RESPONSE,
    )

    assert phase2_report.ctcl_state == "CTCL_FINAL_PENDING"
    assert finalized.ctcl_state == "finalized"
    assert finalized.as_json()["ctcl"] == {
        "state": "finalized",
        "instant_id": CTCL_INSTANT_ID,
        "register_response": CTCL_REGISTER_RESPONSE,
        "retrieve_response": CTCL_RETRIEVE_RESPONSE,
    }
    assert finalized.as_json()["signature_presence"] == "not_performed"
    assert finalized.compatibility_subject_id == phase2_report.compatibility_subject_id
    assert finalized.receipt_id is not None
    payload_without_receipt_id = finalized.as_json()
    del payload_without_receipt_id["receipt_id"]
    assert finalized.receipt_id == sha256_ref(payload_without_receipt_id)


def test_final_receipt_id_commits_to_all_finalized_evidence(phase2_report):
    baseline = finalize_basic_phase2(
        phase2_report,
        ctcl_instant_id=CTCL_INSTANT_ID,
        register_response=CTCL_REGISTER_RESPONSE,
        retrieve_response=CTCL_RETRIEVE_RESPONSE,
    )
    changed_register = copy.deepcopy(CTCL_REGISTER_RESPONSE)
    changed_register["label"] = "changed CTCL evidence"
    changed_integration = copy.deepcopy(phase2_report.integration)
    changed_integration["raw_export_sha256"] = "0" * 64
    changed_tests = copy.deepcopy(phase2_report.sedb_tests)
    changed_tests["own_execution"]["passed"] = 188
    changed_control = replace(
        phase2_report.executed_controls[0],
        injected_change="changed executed-control evidence",
    )
    mutations = (
        (
            replace(
                phase2_report,
                phase1_projection_head="evt_resident_registered_changed",
            ),
            CTCL_REGISTER_RESPONSE,
        ),
        (
            replace(phase2_report, integration=changed_integration),
            CTCL_REGISTER_RESPONSE,
        ),
        (
            replace(phase2_report, sedb_tests=changed_tests),
            CTCL_REGISTER_RESPONSE,
        ),
        (
            replace(
                phase2_report,
                executed_controls=(
                    changed_control,
                    *phase2_report.executed_controls[1:],
                ),
            ),
            CTCL_REGISTER_RESPONSE,
        ),
        (
            replace(phase2_report, error_codes=("injected_error",)),
            CTCL_REGISTER_RESPONSE,
        ),
        (phase2_report, changed_register),
    )

    for mutated_report, register_response in mutations:
        finalized = finalize_basic_phase2(
            mutated_report,
            ctcl_instant_id=CTCL_INSTANT_ID,
            register_response=register_response,
            retrieve_response=CTCL_RETRIEVE_RESPONSE,
        )

        assert finalized.compatibility_subject_id == baseline.compatibility_subject_id
        assert finalized.receipt_id != baseline.receipt_id


@pytest.mark.parametrize(
    ("register_response", "retrieve_response", "error_code"),
    [
        (
            {
                **CTCL_REGISTER_RESPONSE,
                "id": "ctcl:instant:wrong-register",
                "meta": {"id": CTCL_INSTANT_ID},
            },
            CTCL_RETRIEVE_RESPONSE,
            "ctcl_registration_mismatch",
        ),
        (
            CTCL_REGISTER_RESPONSE,
            {
                **CTCL_RETRIEVE_RESPONSE,
                "id": "ctcl:instant:wrong-retrieval",
                "meta": {"id": CTCL_INSTANT_ID},
            },
            "ctcl_retrieval_mismatch",
        ),
    ],
)
def test_ctcl_finalization_requires_authoritative_top_level_ids(
    phase2_report, register_response, retrieve_response, error_code
):
    with pytest.raises(RALValidationError, match=error_code):
        finalize_basic_phase2(
            phase2_report,
            ctcl_instant_id=CTCL_INSTANT_ID,
            register_response=register_response,
            retrieve_response=retrieve_response,
        )


def test_pending_receipt_cannot_be_written_as_final(phase2_report, tmp_path):
    with pytest.raises(RALValidationError, match="ctcl_final_pending"):
        write_basic_phase2_receipt(
            phase2_report,
            tmp_path / "VALIDATION_BASIC_PHASE2.json",
        )


def test_finalized_receipt_is_written_canonically_once(phase2_report, tmp_path):
    finalized = finalize_basic_phase2(
        phase2_report,
        ctcl_instant_id=CTCL_INSTANT_ID,
        register_response=CTCL_REGISTER_RESPONSE,
        retrieve_response=CTCL_RETRIEVE_RESPONSE,
    )
    destination = tmp_path / "VALIDATION_BASIC_PHASE2.json"

    written = write_basic_phase2_receipt(finalized, destination)

    assert written == destination
    assert destination.read_bytes() == canonical_bytes(finalized.as_json()) + b"\n"
    with pytest.raises(FileExistsError):
        write_basic_phase2_receipt(finalized, destination)


def test_writer_rejects_contradiction_even_when_report_says_passed(
    phase2_report, tmp_path
):
    differential = copy.deepcopy(phase2_report.differential)
    differential["passed"] = True
    differential["counts"]["contradiction"] = 1
    finalized = finalize_for_test(
        replace(phase2_report, differential=differential)
    )

    assert_write_rejected(
        finalized, tmp_path, "sedb_differential_invalid"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("executed", False), ("observed_code", "fault_not_detected")],
)
def test_writer_rejects_unexecuted_or_mismatched_control(
    phase2_report, tmp_path, field, value
):
    control = replace(phase2_report.executed_controls[0], **{field: value})
    finalized = finalize_for_test(
        replace(
            phase2_report,
            executed_controls=(control, *phase2_report.executed_controls[1:]),
        )
    )

    assert_write_rejected(finalized, tmp_path, "phase2_controls_invalid")


@pytest.mark.parametrize(
    ("report_field", "error_code"),
    [
        ("phase1a_report", "phase1a_gate_failed"),
        ("phase1bc_report", "phase1bc_gate_failed"),
    ],
)
def test_writer_rejects_failed_phase_report(
    phase2_report, tmp_path, report_field, error_code
):
    phase = copy.deepcopy(getattr(phase2_report, report_field))
    phase["passed"] = False
    finalized = finalize_for_test(replace(phase2_report, **{report_field: phase}))

    assert_write_rejected(finalized, tmp_path, error_code)


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("database_integrity", "corrupt", "sedb_integrity_failed"),
        ("records_match", False, "sedb_records_mismatch"),
        ("exported_record_count", 2, "sedb_record_count_mismatch"),
    ],
)
def test_writer_rejects_failed_or_inconsistent_integration(
    phase2_report, tmp_path, field, value, error_code
):
    integration = copy.deepcopy(phase2_report.integration)
    integration[field] = value
    finalized = finalize_for_test(
        replace(phase2_report, integration=integration)
    )

    assert_write_rejected(finalized, tmp_path, error_code)


def test_writer_rejects_report_errors_before_writing(phase2_report, tmp_path):
    finalized = finalize_for_test(
        replace(phase2_report, error_codes=("injected_error",))
    )

    assert_write_rejected(finalized, tmp_path, "phase2_error_codes_present")


def test_writer_rejects_stale_final_receipt_id(phase2_report, tmp_path):
    finalized = replace(
        finalize_for_test(phase2_report),
        receipt_id="sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64,
    )

    assert_write_rejected(finalized, tmp_path, "receipt_id_mismatch")


def test_writer_rejects_report_that_does_not_pass(phase2_report, tmp_path):
    finalized = replace(finalize_for_test(phase2_report), passed=False)

    assert_write_rejected(finalized, tmp_path, "phase2_report_not_passed")


def test_writer_requires_exact_three_differential_count_keys(
    phase2_report, tmp_path
):
    differential = copy.deepcopy(phase2_report.differential)
    differential["counts"]["future_class"] = 0
    finalized = finalize_for_test(
        replace(phase2_report, differential=differential)
    )

    assert_write_rejected(
        finalized, tmp_path, "sedb_differential_invalid"
    )


def test_writer_requires_exact_five_control_names(phase2_report, tmp_path):
    control = replace(
        phase2_report.executed_controls[0], name="unexpected_control"
    )
    finalized = finalize_for_test(
        replace(
            phase2_report,
            executed_controls=(control, *phase2_report.executed_controls[1:]),
        )
    )

    assert_write_rejected(finalized, tmp_path, "phase2_controls_invalid")


def test_writer_rechecks_finalized_ctcl_top_level_ids(phase2_report, tmp_path):
    finalized = finalize_for_test(phase2_report)
    register_response = copy.deepcopy(finalized.ctcl_register_response)
    register_response["id"] = "ctcl:instant:changed-after-finalization"
    corrupted = replace(
        finalized, ctcl_register_response=register_response
    )

    assert_write_rejected(corrupted, tmp_path, "ctcl_registration_mismatch")


def test_writer_rechecks_compatibility_subject_id(phase2_report, tmp_path):
    finalized = replace(
        finalize_for_test(phase2_report),
        compatibility_subject_id=(
            "sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64
        ),
    )

    assert_write_rejected(
        finalized, tmp_path, "compatibility_subject_id_mismatch"
    )


def test_writer_rejects_unverified_manifest_relationship(
    phase2_report, tmp_path
):
    manifest = copy.deepcopy(phase2_report.manifest)
    manifest["verified"] = False
    finalized = finalize_for_test(replace(phase2_report, manifest=manifest))

    assert_write_rejected(finalized, tmp_path, "manifest_verification_failed")


def test_writer_rejects_changed_inherited_sedb_test_evidence(
    phase2_report, tmp_path
):
    sedb_tests = copy.deepcopy(phase2_report.sedb_tests)
    sedb_tests["own_execution"]["passed"] = 188
    finalized = finalize_for_test(
        replace(phase2_report, sedb_tests=sedb_tests)
    )

    assert_write_rejected(finalized, tmp_path, "sedb_test_evidence_invalid")


def test_task5_evidence_reference_resolves_to_a_tracked_file(phase2_report):
    relative = phase2_report.sedb_tests["own_execution"]["inherited_from"]

    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == relative
    assert (ROOT / relative).is_file()
    assert relative in phase2_report.as_json()["evidence_refs"]
