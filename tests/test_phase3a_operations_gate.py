from pathlib import Path

from sedb_ral.phase3a_operations import (
    EXPECTED_CASE_IDS,
    validate_phase3a_operations,
)

ROOT = Path(__file__).parents[1]


def test_r3b_a_acceptance_inventory_and_side_effects():
    report = validate_phase3a_operations(ROOT)
    value = report.to_dict()
    assert report.passed is True
    assert report.case_ids == EXPECTED_CASE_IDS
    assert report.repeated_run_match is True
    assert value["candidate_version"] == "0.5.0a1"
    for field in (
        "production_root_writes",
        "real_applicants",
        "private_reads",
        "network_calls",
        "external_sends",
        "fabric_events",
    ):
        assert value[field] == 0
