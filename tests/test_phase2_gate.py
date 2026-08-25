import copy
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import sedb_ral.phase2 as phase2_module
from scripts.validate_phase2 import main as script_main
from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.cli import main as cli_main
from sedb_ral.contracts import validate_contract
from sedb_ral.errors import RALValidationError
from sedb_ral.no_send import scan_task5_no_send
from sedb_ral.phase2 import (
    finalize_basic_phase2,
    validate_basic_phase2,
    write_basic_phase2_receipt,
)

ROOT = Path(__file__).parents[1]
ARCHIVE = Path(
    os.environ.get(
        "SEDB_V04B_ARCHIVE",
        ROOT.parent / "SEDB/releases/SEDB-v0.4B-local.zip",
    )
)
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


def coherently_reidentify(report):
    subject_id = sha256_ref(
        {
            "kind": "sedb-ral-basic-phase2-receipt",
            "adoption_profile_id": report.adoption_profile_id,
            "adoption_profile_version": report.adoption_profile_version,
            "mapping_profile_id": report.mapping_profile_id,
            "mapping_profile_version": report.mapping_profile_version,
            "archive_sha256": report.archive["sha256"],
            "mapping_profile_digest": report.mapping_profile_digest,
        }
    )
    identified = replace(
        report,
        compatibility_subject_id=subject_id,
        receipt_id=None,
    )
    payload = identified.as_json()
    del payload["receipt_id"]
    return replace(identified, receipt_id=sha256_ref(payload))


def assert_write_rejected(report, tmp_path, error_code):
    destination = tmp_path / "VALIDATION_BASIC_PHASE2.json"
    with pytest.raises(RALValidationError, match=error_code):
        write_basic_phase2_receipt(report, destination)
    assert not destination.exists()


def test_basic_phase2_gate_passes_exact_archive(phase2_report):
    assert phase2_report.passed is True
    assert phase2_report.diff_counts["expected_by_mapping"] >= 1
    assert phase2_report.diff_counts["unmapped"] == 0
    assert phase2_report.diff_counts["contradiction"] == 0


def test_unknown_actual_field_is_unmapped_and_overall_passes(monkeypatch):
    if not ARCHIVE.is_file():
        pytest.skip("archive_unavailable")
    run_integration = phase2_module._run_task5_integration

    def run_with_unknown_field(*args, **kwargs):
        result = run_integration(*args, **kwargs)
        exported_records = copy.deepcopy(result.exported_records)
        exported_records[0]["values"]["sedb_unmapped.future"] = {
            "source": "isolated-sedb-export"
        }
        return replace(
            result,
            exported_records=tuple(exported_records),
            records_match=False,
        )

    monkeypatch.setattr(phase2_module, "_run_task5_integration", run_with_unknown_field)

    report = validate_basic_phase2(ROOT, ARCHIVE)

    assert report.passed is True
    assert report.integration["records_match"] is False
    assert report.diff_counts == {
        "expected_by_mapping": 1,
        "unmapped": 1,
        "contradiction": 0,
    }


def test_mapped_actual_field_contradiction_fails_overall(monkeypatch):
    if not ARCHIVE.is_file():
        pytest.skip("archive_unavailable")
    run_integration = phase2_module._run_task5_integration

    def run_with_mapped_contradiction(*args, **kwargs):
        result = run_integration(*args, **kwargs)
        exported_records = copy.deepcopy(result.exported_records)
        exported_records[0]["values"]["ral.resident_id"] = "resident:wrong"
        return replace(
            result,
            exported_records=tuple(exported_records),
            records_match=False,
        )

    monkeypatch.setattr(
        phase2_module,
        "_run_task5_integration",
        run_with_mapped_contradiction,
    )

    report = validate_basic_phase2(ROOT, ARCHIVE)

    assert report.passed is False
    assert report.integration["records_match"] is False
    assert report.diff_counts == {
        "expected_by_mapping": 1,
        "unmapped": 0,
        "contradiction": 1,
    }
    assert report.error_codes == ("sedb_mapping_contradiction",)


def test_phase2_gate_rejects_injected_task5_network_call(tmp_path, monkeypatch):
    if not ARCHIVE.is_file():
        pytest.skip("archive_unavailable")
    injected_script = tmp_path / "validate_sedb_v04b.py"
    injected_script.write_text(
        (ROOT / "scripts/validate_sedb_v04b.py").read_text(encoding="utf-8")
        + "\nimport socket\nsocket.create_connection(('example.test', 443))\n",
        encoding="utf-8",
    )
    injected_findings = scan_task5_no_send(injected_script)
    assert "forbidden_call:socket.create_connection" in {
        finding.code for finding in injected_findings
    }
    monkeypatch.setattr(
        phase2_module,
        "scan_task5_no_send",
        lambda path: injected_findings,
    )

    report = validate_basic_phase2(ROOT, ARCHIVE)

    assert report.passed is False
    assert "no_send_violation" in report.error_codes


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
        "expected_by_mapping": 1,
        "unmapped": 0,
        "contradiction": 0,
    }
    assert payload["differential"]["differences"] == [
        {
            "path": "records[resident:test].values.ral.authority",
            "classification": "expected_by_mapping",
            "expected": {
                "presence": "present",
                "value": {
                    "authority_ref": "authority:test:1",
                    "authority_digest": (
                        "sha256:sedb-ral-json-nfc-codepoint-v1:"
                        "dab92e51e9799b4409c9de2b4a1132b07a35694dd5a8aff614e1babde83487d9"
                    ),
                },
            },
            "actual": {"presence": "missing"},
            "rule_id": "authority",
        }
    ]
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package.name", "attacker-sedb"),
        ("package.version", "0.4.0b2"),
        ("package.source_commit", "0" * 40),
        (
            "mapping_profile_digest",
            "sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64,
        ),
    ],
    ids=["package-name", "package-version", "source-commit", "mapping-digest"],
)
def test_v02_receipt_schema_binds_exact_adopted_profile_facts(
    phase2_report, field, value
):
    payload = finalize_for_test(phase2_report).as_json()
    if field.startswith("package."):
        payload["package"][field.removeprefix("package.")] = value
    else:
        payload[field] = value

    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(
            "sedb-compatibility-receipt.schema.json",
            payload,
            ROOT / "src/sedb_ral/schemas",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package.name", "attacker-sedb"),
        ("package.version", "0.4.0b2"),
        ("package.source_commit", "0" * 40),
        (
            "mapping_profile_digest",
            "sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64,
        ),
    ],
    ids=["package-name", "package-version", "source-commit", "mapping-digest"],
)
def test_writer_rejects_coherently_reidentified_profile_tampering(
    phase2_report, tmp_path, field, value
):
    finalized = finalize_for_test(phase2_report)
    if field.startswith("package."):
        package = copy.deepcopy(finalized.package)
        package[field.removeprefix("package.")] = value
        tampered = replace(finalized, package=package)
    else:
        tampered = replace(finalized, **{field: value})
    tampered = coherently_reidentify(tampered)

    assert_write_rejected(tampered, tmp_path, "sedb_profile_identity_mismatch")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adoption_profile_id", "attacker-adoption"),
        ("adoption_profile_version", "2"),
        ("mapping_profile_id", "attacker-mapping"),
        ("mapping_profile_version", "2"),
        ("archive.filename", "SEDB-v0.4B-other.zip"),
        ("archive.size", 8980053),
        ("archive.sha256", "0" * 64),
        ("manifest.path", "MANIFEST.other"),
        ("manifest.expected_entry_count", 113),
    ],
)
def test_writer_retains_existing_exact_profile_constants(
    phase2_report, tmp_path, field, value
):
    finalized = finalize_for_test(phase2_report)
    if field.startswith("archive."):
        archive = copy.deepcopy(finalized.archive)
        archive[field.removeprefix("archive.")] = value
        tampered = replace(finalized, archive=archive)
    elif field.startswith("manifest."):
        manifest = copy.deepcopy(finalized.manifest)
        manifest[field.removeprefix("manifest.")] = value
        tampered = replace(finalized, manifest=manifest)
    else:
        tampered = replace(finalized, **{field: value})
    tampered = coherently_reidentify(tampered)

    assert_write_rejected(tampered, tmp_path, "sedb_profile_identity_mismatch")


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
    finalized = finalize_for_test(replace(phase2_report, differential=differential))

    assert_write_rejected(finalized, tmp_path, "sedb_differential_invalid")


def test_writer_accepts_nonexact_diagnostics_when_allowed_differences_agree(
    phase2_report, tmp_path
):
    integration = copy.deepcopy(phase2_report.integration)
    integration["records_match"] = False
    integration["exported_record_count"] += 1
    differential = copy.deepcopy(phase2_report.differential)
    differential["counts"]["unmapped"] += 1
    differential["differences"].append(
        {
            "path": "records[resident:test].values.sedb_unmapped.future",
            "classification": "unmapped",
            "expected": {"presence": "missing"},
            "actual": {"presence": "present", "value": "future"},
            "rule_id": None,
        }
    )
    finalized = finalize_for_test(
        replace(
            phase2_report,
            integration=integration,
            differential=differential,
        )
    )
    destination = tmp_path / "VALIDATION_BASIC_PHASE2.json"

    assert write_basic_phase2_receipt(finalized, destination) == destination
    assert destination.is_file()


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


def test_writer_rejects_failed_database_integrity(phase2_report, tmp_path):
    integration = copy.deepcopy(phase2_report.integration)
    integration["database_integrity"] = "corrupt"
    finalized = finalize_for_test(replace(phase2_report, integration=integration))

    assert_write_rejected(finalized, tmp_path, "sedb_integrity_failed")


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


def test_writer_requires_exact_three_differential_count_keys(phase2_report, tmp_path):
    differential = copy.deepcopy(phase2_report.differential)
    differential["counts"]["future_class"] = 0
    finalized = finalize_for_test(replace(phase2_report, differential=differential))

    assert_write_rejected(finalized, tmp_path, "sedb_differential_invalid")


def test_writer_rejects_differential_count_list_mismatch(phase2_report, tmp_path):
    differential = copy.deepcopy(phase2_report.differential)
    differential["counts"]["expected_by_mapping"] += 1
    finalized = finalize_for_test(replace(phase2_report, differential=differential))

    assert_write_rejected(finalized, tmp_path, "sedb_differential_invalid")


def test_writer_requires_exact_five_control_names(phase2_report, tmp_path):
    control = replace(phase2_report.executed_controls[0], name="unexpected_control")
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
    corrupted = replace(finalized, ctcl_register_response=register_response)

    assert_write_rejected(corrupted, tmp_path, "ctcl_registration_mismatch")


def test_writer_rechecks_compatibility_subject_id(phase2_report, tmp_path):
    finalized = replace(
        finalize_for_test(phase2_report),
        compatibility_subject_id=("sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64),
    )

    assert_write_rejected(finalized, tmp_path, "compatibility_subject_id_mismatch")


def test_writer_rejects_unverified_manifest_relationship(phase2_report, tmp_path):
    manifest = copy.deepcopy(phase2_report.manifest)
    manifest["verified"] = False
    finalized = finalize_for_test(replace(phase2_report, manifest=manifest))

    assert_write_rejected(finalized, tmp_path, "manifest_verification_failed")


def test_writer_rejects_changed_inherited_sedb_test_evidence(phase2_report, tmp_path):
    sedb_tests = copy.deepcopy(phase2_report.sedb_tests)
    sedb_tests["own_execution"]["passed"] = 188
    finalized = finalize_for_test(replace(phase2_report, sedb_tests=sedb_tests))

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
