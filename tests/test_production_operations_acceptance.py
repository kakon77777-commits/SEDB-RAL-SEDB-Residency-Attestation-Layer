from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.production_operations_acceptance import (
    validate_production_operations,
    write_production_operations_report,
)


ROOT = Path(__file__).parents[1]


def test_r3b_acceptance_is_complete_and_deterministic():
    first = validate_production_operations(ROOT)
    second = validate_production_operations(ROOT)

    assert first.passed is True
    assert [case.case_id for case in first.cases] == [
        f"R3B-{index:03d}" for index in range(1, 22)
    ]
    assert first.report_digest == second.report_digest
    assert first.effects == {
        "production_residents": 0,
        "production_events": 0,
        "real_applicants": 0,
        "private_reads": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "fabric_events": 0,
        "mcp_calls": 0,
    }


def test_report_writer_is_create_only_and_digest_checked(tmp_path):
    report = validate_production_operations(ROOT)
    output = tmp_path / "r3b-b.json"

    write_production_operations_report(report, output)

    assert output.is_file()
    with pytest.raises(RALValidationError, match="production_operations_report_exists"):
        write_production_operations_report(report, output)
    tampered = replace(report, report_digest="sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64)
    with pytest.raises(RALValidationError, match="production_operations_acceptance_digest_mismatch"):
        write_production_operations_report(tampered, tmp_path / "tampered.json")

