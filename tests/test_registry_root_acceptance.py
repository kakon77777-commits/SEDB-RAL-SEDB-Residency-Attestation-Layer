from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from sedb_ral import __version__
from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registry_root_acceptance import (
    EXPECTED_CASE_IDS,
    EXPECTED_CONTROLS,
    validate_registry_root,
    verify_production_registry_receipt,
    write_registry_root_report,
)
from sedb_ral.registry_root_contracts import (
    APPROVED_ROOT_SCOPES,
    bind_document_digest,
)

ROOT = __import__("pathlib").Path(__file__).parents[1]


@pytest.fixture(scope="module")
def report():
    return validate_registry_root(ROOT)


def test_acceptance_executes_every_P4_case_and_injected_control(report):
    assert report.passed is True
    assert report.case_ids == EXPECTED_CASE_IDS
    assert report.control_names == EXPECTED_CONTROLS
    assert all(item.passed for item in report.cases)
    assert all(item.executed and item.passed for item in report.controls)
    assert report.repeated_run_match is True
    assert report.execution_digest == report.repeated_execution_digest
    assert report.error_codes == ()


def test_acceptance_proves_zero_out_of_scope_side_effects(report):
    value = report.as_json()
    assert value["ledger_event_count"] == 0
    assert value["resident_count"] == 0
    assert value["application_count"] == 0
    assert value["address_count"] == 0
    assert value["private_reads"] == 0
    assert value["network_calls"] == 0
    assert value["external_effects"] == 0
    assert value["production_registry_created"] is False
    assert value["canonical_write_scope"] == "temporary-synthetic-only"


def test_acceptance_report_is_sanitized_and_digest_bound(report):
    value = report.as_json()
    encoded = canonical_bytes(value)
    material = dict(value)
    digest = material.pop("report_digest")

    assert digest == sha256_ref(material)
    lowered = encoded.lower()
    assert b"c:\\users\\" not in lowered
    assert b"owner_sid" not in lowered
    assert b"sddl" not in lowered
    assert b"authority_id" not in lowered
    assert b"native_thread_id" not in lowered


def test_report_writer_is_create_only_and_refuses_tampering(tmp_path, report):
    output = tmp_path / "synthetic.json"
    write_registry_root_report(report, output)
    original = output.read_bytes()
    assert original == canonical_bytes(report.as_json()) + b"\n"

    with pytest.raises(FileExistsError):
        write_registry_root_report(report, output)
    assert output.read_bytes() == original

    tampered = copy.copy(report)
    object.__setattr__(tampered, "report_digest", "sha256:wrong")
    with pytest.raises(RALValidationError) as caught:
        write_registry_root_report(tampered, tmp_path / "tampered.json")
    assert caught.value.code == "registry_root_report_digest_mismatch"


def test_repeated_acceptance_reports_are_canonical_equivalent():
    first = validate_registry_root(ROOT)
    second = validate_registry_root(ROOT)

    assert json.loads(canonical_bytes(first.as_json())) == json.loads(
        canonical_bytes(second.as_json())
    )


def test_validator_script_writes_the_requested_report(tmp_path):
    output = tmp_path / "validator-report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_registry_root.py"),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    written = json.loads(output.read_text(encoding="utf-8"))
    emitted = json.loads(result.stdout)
    assert written == emitted
    assert written["passed"] is True


def test_checked_synthetic_report_replays_under_its_commit_binding():
    checked = json.loads(
        (
            ROOT / "evidence/production-registry-root/2026-08-25-local-synthetic.json"
        ).read_text(encoding="utf-8")
    )
    if checked["candidate_version"] != __version__:
        pytest.skip("checked production evidence belongs to the 0.4.0 baseline")
    live = validate_registry_root(ROOT).as_json()
    live["implementation_commit"] = checked["implementation_commit"]
    material = dict(live)
    material.pop("report_digest")
    live["report_digest"] = sha256_ref(material)

    assert live == checked


def valid_production_receipt():
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-registry-acceptance/0.1",
            "phase": "P3-4",
            "status": "passed",
            "production_root_ref": "AI_RESIDENCE/REGISTRY/SEDB-RAL",
            "source_package_version": "0.4.0",
            "source_commit": "a" * 40,
            "ci": {
                "workflow": "phase3a.yml",
                "run_id": 32841941812,
                "head_commit": "a" * 40,
                "status": "success",
                "successful_jobs": 6,
                "job_count": 6,
            },
            "plan_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "1" * 64,
            "authority_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "2" * 64,
            "authority_scopes": list(APPROVED_ROOT_SCOPES),
            "time_status": "host_wall_clock_unverified",
            "registry_id": "registry:31e5ee61-2909-4f0d-bdaf-d0aa2f77ed92",
            "manifest_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "3" * 64,
            "control_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "4" * 64,
            "canonical_tree_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:"
            + "5" * 64,
            "checkpoint_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "6" * 64,
            "checkpoint_snapshot_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:"
            + "7" * 64,
            "restore_receipt_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:"
            + "8" * 64,
            "rollback_receipt_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:"
            + "9" * 64,
            "restored_byte_map_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:"
            + "a" * 64,
            "acl": {
                "policy_fingerprint_match": True,
                "inheritance_protected": True,
                "required_principal_classes": [
                    "configured_owner",
                    "SYSTEM",
                    "Administrators",
                ],
                "forbidden_write_count": 0,
            },
            "counts": {
                "ledger_events": 0,
                "applications": 0,
                "residents": 0,
                "addresses": 0,
            },
            "effects": {
                "private_reads": 0,
                "network": 0,
                "external": 0,
            },
            "recovery": {
                "storage_scope": "same_volume_local",
                "restore_byte_identical": True,
                "rollback_red_control": "checkpoint_manifest_digest_mismatch",
                "fresh_restore_byte_identical": True,
                "production_digest_unchanged": True,
            },
            "wrapper_history": {
                "initializer_status": "stopped_after_candidate_prepare",
                "publication_resume": "same_plan_core_no_replace",
                "rollback_cli_status": "stopped_before_core_target_creation",
                "rollback_resume": "same_authority_direct_core",
                "cleanup_performed": False,
            },
            "evidence_refs": [
                "evidence/production-registry-root/2026-08-25-local-synthetic.json",
                "docs/runtime/PRODUCTION_REGISTRY_ROOT.md",
            ],
            "not_claimed": [
                "resident_admission",
                "private_access",
                "offsite_backup",
                "volume_loss_recovery",
                "ctcl_registered_time",
                "cleanup",
            ],
        },
        "receipt_digest",
    )


def test_production_receipt_is_strict_digest_bound_and_sanitized():
    receipt = valid_production_receipt()
    verify_production_registry_receipt(receipt)

    tampered = copy.deepcopy(receipt)
    tampered["counts"]["residents"] = 1
    with pytest.raises(RALValidationError) as caught:
        verify_production_registry_receipt(tampered)
    assert caught.value.code == "production_registry_receipt_digest_mismatch"

    leaked = copy.deepcopy(receipt)
    leaked.pop("receipt_digest")
    leaked["production_root_ref"] = r"C:\Users\someone\private"
    leaked = bind_document_digest(leaked, "receipt_digest")
    with pytest.raises(RALValidationError) as caught:
        verify_production_registry_receipt(leaked)
    assert caught.value.code == "production_registry_receipt_sensitive_material"


def test_validator_script_verifies_a_production_receipt(tmp_path):
    receipt_path = tmp_path / "production.json"
    receipt_path.write_bytes(canonical_bytes(valid_production_receipt()))

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_registry_root.py"),
            "--verify-production-receipt",
            str(receipt_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema": "sedb-ral.production-registry-receipt-verification/0.1",
        "valid": True,
    }
