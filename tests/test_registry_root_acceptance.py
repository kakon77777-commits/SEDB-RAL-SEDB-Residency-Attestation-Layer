from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registry_root_acceptance import (
    EXPECTED_CASE_IDS,
    EXPECTED_CONTROLS,
    validate_registry_root,
    write_registry_root_report,
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


def test_checked_synthetic_report_replays_exactly():
    checked = json.loads(
        (
            ROOT
            / "evidence/production-registry-root/2026-08-25-local-synthetic.json"
        ).read_text(encoding="utf-8")
    )
    live = validate_registry_root(ROOT).as_json()

    assert live == checked
