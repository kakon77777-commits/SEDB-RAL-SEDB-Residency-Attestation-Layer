from __future__ import annotations

import json
from pathlib import Path

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_acceptance import (
    OWNER_PLAN_CASES,
    _effect_injection_controls,
    validate_registration_wave,
    write_registration_wave_report,
)


@pytest.fixture(scope="module")
def acceptance(tmp_path_factory):
    return validate_registration_wave(tmp_path_factory.mktemp("wave-acceptance"))


def expected_positive_effect_manifest() -> dict[str, list[str]]:
    path = (
        Path(__file__).parent
        / "fixtures/registration_wave/expected-positive-effects.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_acceptance_has_every_unique_case_and_executed_control(acceptance):
    assert tuple(case.case_id for case in acceptance.cases) == tuple(
        f"W1-{index:03d}" for index in range(1, 54)
    )
    assert all(
        case.executed and case.passed
        for case in acceptance.cases
        if case.case_id not in OWNER_PLAN_CASES
    )
    assert {
        case.case_id: case.status for case in acceptance.cases if not case.executed
    } == {
        case_id: "NOT_RUN_OWNER_PLAN_REQUIRED"
        for case_id in sorted(OWNER_PLAN_CASES)
    }
    assert acceptance.passed is True
    assert acceptance.production_wave_run == "NOT_RUN"
    assert acceptance.live_limen_b6a == "NOT_RUN"
    assert acceptance.production_root_status == "NOT_READ"


def test_positive_effects_are_exact_refs_and_forbidden_controls_discriminate(
    acceptance,
):
    assert {
        name: list(refs) for name, refs in acceptance.effects.allowed_refs().items()
    } == expected_positive_effect_manifest()
    assert acceptance.effects.fixture_reads == 9
    assert acceptance.effects.staging_writes == 28
    assert acceptance.effects.synthetic_ledger_writes == 12
    assert acceptance.effects.synthetic_receipt_writes == 4
    assert acceptance.effects.forbidden_nonzero_dimensions() == ()
    assert _effect_injection_controls() == {
        "production_reads": True,
        "production_writes": True,
        "private_reads": True,
        "private_writes": True,
        "network_calls": True,
        "provider_calls": True,
        "fabric_calls": True,
        "mcp_calls": True,
        "external_cli_calls": True,
    }


def test_two_runs_are_deterministic_and_report_is_create_only(
    acceptance, tmp_path
):
    assert acceptance.first_run_digest == acceptance.second_run_digest
    output = tmp_path / "registration-wave-acceptance.json"

    write_registration_wave_report(acceptance, output)
    value = json.loads(output.read_text(encoding="utf-8"))

    assert value["status"] == "pass"
    assert value["executed_count"] == 47
    assert value["owner_plan_not_run_count"] == 6
    assert value["report_digest"] == acceptance.report_digest
    with pytest.raises(RALValidationError, match="output_exists"):
        write_registration_wave_report(acceptance, output)
