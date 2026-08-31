from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import sedb_ral.registration_wave_acceptance as acceptance_module
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_acceptance import (
    OWNER_PLAN_CASES,
    _build_acceptance_report,
    _effect_injection_controls,
    _run_positive,
    validate_registration_wave,
    write_registration_wave_report,
)
from sedb_ral.registration_wave_context import WaveEffectJournal


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
    executed = [case for case in acceptance.cases if case.executed]
    assert len({case.evidence_digest for case in executed}) == 47
    assert all(
        set(case.control_evidence)
        == {
            "population",
            "negative_and_adjacent_positive",
            "adjacent_positive_run_digest",
        }
        for case in executed
    )


def test_positive_effects_are_exact_refs_and_forbidden_controls_discriminate(
    acceptance, tmp_path
):
    assert {
        name: list(refs) for name, refs in acceptance.effects.allowed_refs().items()
    } == expected_positive_effect_manifest()
    assert acceptance.effects.fixture_reads == 9
    assert acceptance.effects.staging_writes == 19
    assert acceptance.effects.synthetic_ledger_writes == 12
    assert acceptance.effects.synthetic_receipt_writes == 4
    assert acceptance.effects.forbidden_nonzero_dimensions() == ()
    assert _effect_injection_controls(tmp_path / "effect-controls") == {
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
    for dimension in (
        "production_reads",
        "production_writes",
        "private_reads",
        "private_writes",
        "network_calls",
        "provider_calls",
        "fabric_calls",
        "mcp_calls",
        "external_cli_calls",
    ):
        journal = WaveEffectJournal()
        context = acceptance_module._marker_context(
            tmp_path / "report-controls",
            dimension,
            tmp_path / "report-controls" / dimension / "target",
            journal,
        )
        context.record_effect(dimension, f"injected:{dimension}")
        assert replace(acceptance, effects=journal).passed is False


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


def test_runtime_effect_injection_cannot_be_detached_from_reported_journal(
    tmp_path, monkeypatch
):
    original = acceptance_module.simulate_wave_slot
    injected_slots = set()

    def injected(context, *args, **kwargs):
        slot_index = args[0].slot_request.slot_index
        if slot_index not in injected_slots:
            context.record_effect(
                "network_calls", f"injected:runtime-network:slot-{slot_index}"
            )
            injected_slots.add(slot_index)
        return original(context, *args, **kwargs)

    monkeypatch.setattr(acceptance_module, "simulate_wave_slot", injected)
    observed = _run_positive(tmp_path / "runtime-injection")
    original_build_slot_request = acceptance_module.build_slot_request
    request_calls = []

    def tracked_request(plan, slot_index, prefix, ledger_state):
        request_calls.append(
            {
                "slot_index": slot_index,
                "head": ledger_state["expected_ledger_head"],
                "count": ledger_state["ledger_event_count"],
            }
        )
        return original_build_slot_request(plan, slot_index, prefix, ledger_state)

    monkeypatch.setattr(
        acceptance_module, "build_slot_request", tracked_request
    )
    report = _build_acceptance_report(tmp_path / "injected-report", observed, observed)

    assert observed.effects.network_calls == 3
    assert observed.effects.forbidden_nonzero_dimensions() == ("network_calls",)
    assert report.passed is False
    assert {call["slot_index"] for call in request_calls} == {1, 2, 3}
    assert {call["head"] for call in request_calls if call["slot_index"] == 2} == {
        None,
        observed.slot_results[0].post_head,
    }
    assert any(
        call["slot_index"] == 3
        and call["head"] == observed.slot_results[0].post_head
        for call in request_calls
    )
