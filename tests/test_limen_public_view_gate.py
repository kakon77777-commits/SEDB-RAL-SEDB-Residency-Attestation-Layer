import json
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.limen_export_acceptance import (
    EXPECTED_CASE_IDS,
    EXPECTED_CONTROLS,
    validate_limen_public_view,
    write_limen_public_view_report,
)

ROOT = Path(__file__).parents[1]


def test_export_gate_has_exact_inventory_and_zero_production_effects(tmp_path):
    report = validate_limen_public_view(ROOT, output_root=tmp_path)

    assert report.passed is True
    assert report.case_ids == EXPECTED_CASE_IDS
    assert report.control_names == EXPECTED_CONTROLS
    assert all(item.passed for item in report.cases)
    assert all(item.executed and item.passed for item in report.controls)
    assert report.network_calls == 0
    assert report.private_reads == 0
    assert report.registry_writes == 0
    assert report.real_resident_count == 0
    assert report.synthetic_resident_count == 2
    assert report.repeated_run_match is True
    assert report.error_codes == ()
    assert not list(tmp_path.iterdir())


def test_export_gate_is_byte_deterministic_across_outer_runs(tmp_path):
    first = validate_limen_public_view(ROOT, output_root=tmp_path / "first")
    second = validate_limen_public_view(ROOT, output_root=tmp_path / "second")

    assert canonical_bytes(first.as_json()) == canonical_bytes(second.as_json())
    assert first.report_digest == second.report_digest


def test_export_report_writes_canonically_once(tmp_path):
    report = validate_limen_public_view(ROOT, output_root=tmp_path / "work")
    destination = tmp_path / "limen-public-view.json"

    assert write_limen_public_view_report(report, destination) == destination
    assert destination.read_bytes() == canonical_bytes(report.as_json()) + b"\n"
    with pytest.raises(FileExistsError):
        write_limen_public_view_report(report, destination)


def test_export_report_keeps_consumer_and_private_boundaries_explicit(tmp_path):
    value = validate_limen_public_view(ROOT, output_root=tmp_path).as_json()

    assert value["limen_consumption_verified"] is False
    assert value["host_enforcement_verified"] is False
    assert value["private_residence_accessed"] is False
    assert value["production_registry_configured"] is False
    assert set(value["not_claimed"]) >= {
        "limen_consumption",
        "real_identity_resolution",
        "host_enforcement",
        "private_access",
    }


def test_checked_in_export_evidence_is_canonical_and_self_bound():
    path = ROOT / "evidence/limen-public-view/2026-08-25-local.json"
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
