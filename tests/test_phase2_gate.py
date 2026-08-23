import json
from pathlib import Path

import pytest

from scripts.validate_phase2 import main as script_main
from sedb_ral.canonical import canonical_bytes
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
    "result": {
        "id": CTCL_INSTANT_ID,
        "registered": True,
        "share_url": "https://ctcl.example.test/instant/7",
    }
}
CTCL_RETRIEVE_RESPONSE = {
    "result": {
        "instant": {"id": CTCL_INSTANT_ID},
        "retrieved": True,
    }
}


@pytest.fixture(scope="module")
def phase2_report():
    if not ARCHIVE.is_file():
        pytest.skip("archive_unavailable")
    return validate_basic_phase2(ROOT, ARCHIVE)


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


def test_ctcl_finalization_rejects_a_mismatched_retrieval(phase2_report):
    wrong_retrieval = {
        "result": {
            "instant": {"id": "ctcl:instant:other"},
            "retrieved": True,
        }
    }

    with pytest.raises(RALValidationError, match="ctcl_retrieval_mismatch"):
        finalize_basic_phase2(
            phase2_report,
            ctcl_instant_id=CTCL_INSTANT_ID,
            register_response=CTCL_REGISTER_RESPONSE,
            retrieve_response=wrong_retrieval,
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
