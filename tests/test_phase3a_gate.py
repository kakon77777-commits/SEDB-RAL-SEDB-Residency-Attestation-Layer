import json
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.phase3a import (
    EXPECTED_CASE_IDS,
    EXPECTED_CONTROLS,
    validate_phase3a,
    write_phase3a_report,
)

ROOT = Path(__file__).parents[1]


def test_phase3a_gate_reports_exact_inventory(tmp_path):
    report = validate_phase3a(ROOT, output_root=tmp_path)

    assert report.passed is True
    assert report.case_ids == EXPECTED_CASE_IDS
    assert report.control_names == EXPECTED_CONTROLS
    assert all(item.passed for item in report.cases)
    assert all(item.executed for item in report.controls)
    assert report.network_calls == 0
    assert report.private_reads == 0
    assert report.real_applicant_count == 0
    assert report.synthetic_applicant_count == 2
    assert report.repeated_run_match is True
    assert report.error_codes == ()
    assert not list(tmp_path.iterdir())


def test_phase3a_gate_is_byte_deterministic_across_outer_runs(tmp_path):
    first = validate_phase3a(ROOT, output_root=tmp_path / "first")
    second = validate_phase3a(ROOT, output_root=tmp_path / "second")

    assert canonical_bytes(first.as_json()) == canonical_bytes(second.as_json())
    assert first.report_digest == second.report_digest


def test_phase3a_report_writes_canonically_once(tmp_path):
    report = validate_phase3a(ROOT, output_root=tmp_path / "work")
    destination = tmp_path / "phase3a.json"

    written = write_phase3a_report(report, destination)

    assert written == destination
    assert destination.read_bytes() == canonical_bytes(report.as_json()) + b"\n"
    assert json.loads(destination.read_text(encoding="utf-8"))["passed"] is True
    with pytest.raises(FileExistsError):
        write_phase3a_report(report, destination)


def test_phase3a_report_keeps_real_boundaries_explicit(tmp_path):
    report = validate_phase3a(ROOT, output_root=tmp_path)
    value = report.as_json()

    assert value["canonical_write_scope"] == "temporary-synthetic-only"
    assert value["production_registry_created"] is False
    assert value["registrar_mcp_implemented"] is False
    assert value["limen_b6_implemented"] is False
    assert value["private_residence_accessed"] is False
    assert value["release_or_deployment"] is False
    assert set(value["not_claimed"]) >= {
        "real_applicant_registration",
        "production_registry",
        "limen_b6",
        "private_residence_access",
    }


def test_checked_in_phase3a_evidence_is_canonical_and_self_bound():
    path = ROOT / "evidence/phase3a/2026-08-25-local.json"
    raw = path.read_bytes()
    value = json.loads(raw)
    report_digest = value.pop("report_digest")

    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert b"\r" not in raw
    assert canonical_bytes({**value, "report_digest": report_digest}) + b"\n" == raw
    assert sha256_ref(value) == report_digest
    assert tuple(value["case_ids"]) == EXPECTED_CASE_IDS
    assert tuple(item["name"] for item in value["controls"]) == EXPECTED_CONTROLS
