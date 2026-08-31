from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from test_registration_wave_engine import CTCL, engine_context, setup_slot_one
from test_registration_wave_intake import claim, context, host, ids, item, raw_item
from test_registration_wave_plan import (
    candidates as make_candidates,
)
from test_registration_wave_plan import (
    checkpoint,
    policy,
    registry_status,
)
from test_registration_wave_policy import (
    install_active_dormant,
    verified_approvals,
)
from test_registration_wave_readback import (
    published_storage as readback_published_storage,
)
from test_registration_wave_readback import wave_state

from sedb_ral.canonical import canonical_bytes, loads_strict
from sedb_ral.cli import main
from sedb_ral.registry_root import registry_root_status


def write_json(path: Path, value: object) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path


@pytest.fixture
def published_storage(tmp_path):
    return readback_published_storage.__wrapped__(tmp_path)


def raw_applicant_value(index: int) -> dict[str, object]:
    raw = raw_item(index)
    return {
        "provider": raw.provider,
        "adapter_kind": raw.adapter_kind,
        "native_thread_id": raw.native_thread_id,
        "native_turn_id": raw.native_turn_id,
        "source_item_role": raw.source_item_role,
        "source_item_kind": raw.source_item_kind,
        "source_item_status": raw.source_item_status,
        "source_item_parent_thread_id": raw.source_item_parent_thread_id,
        "source_item_parent_turn_id": raw.source_item_parent_turn_id,
        "applicant_item_ref": raw.applicant_item_ref,
        "content": claim(index),
    }


def candidate_bundle(index: int) -> dict[str, object]:
    id_value = asdict(ids(index))
    id_value["address_ids"] = list(id_value["address_ids"])
    id_value["claim_ids"] = list(id_value["claim_ids"])
    return {
        "claim": claim(index),
        "item": item(index),
        "host": host(index),
        "raw_item": raw_applicant_value(index),
        "ids": id_value,
    }


def context_value(selected) -> dict[str, object]:
    return {
        "mode": selected.mode.value,
        "fixture_root": str(selected.fixture_root),
        "target_root": str(selected.target_root),
        "fixture_marker_ref": selected.fixture_marker_ref,
        "fixture_marker_digest": selected.fixture_marker_digest,
        "forbidden_roots": [str(value) for value in selected.forbidden_roots],
    }


def raw_principal_value(raw) -> dict[str, object]:
    return {
        "provider": raw.provider,
        "adapter_kind": raw.adapter_kind,
        "native_thread_id": raw.native_thread_id,
        "native_turn_id": raw.native_turn_id,
        "source_item_role": raw.source_item_role,
        "source_item_kind": raw.source_item_kind,
        "source_item_status": raw.source_item_status,
        "source_item_parent_thread_id": raw.source_item_parent_thread_id,
        "source_item_parent_turn_id": raw.source_item_parent_turn_id,
        "source_item_ref": raw.source_item_ref,
        "content": loads_strict(raw.content_bytes.decode("utf-8")),
    }


def approval_value(approval) -> dict[str, object]:
    return {
        "approval": approval.approval.to_dict(),
        "raw_item": raw_principal_value(approval.raw_item),
        "host": asdict(approval.host),
        "expected_principal_ref": approval.approval.principal_ref,
    }


def time_value() -> dict[str, object]:
    return {
        "now_ref": "time:now",
        "now_epoch_ns": 200,
        "valid_from_ref": "time:start",
        "valid_from_epoch_ns": 100,
        "expires_at_ref": "time:end",
        "expires_at_epoch_ns": 300,
    }


def policy_time_value() -> dict[str, object]:
    return {
        "now_ref": "time:policy-now",
        "now_epoch_ns": 200,
        "valid_from_ref": "ctcl:instant:policy-start",
        "valid_from_epoch_ns": 100,
        "expires_at_ref": "ctcl:instant:policy-end",
        "expires_at_epoch_ns": 300,
    }


COMMANDS = (
    "validate-intake",
    "prepare-slot",
    "build-plan",
    "policy-plan",
    "policy-status",
    "slot-plan",
    "slot-admit",
    "slot-recover",
    "wave-status",
    "export-readback",
)


@pytest.mark.parametrize("command", COMMANDS)
def test_registration_wave_commands_require_an_explicit_request(command, capfd):
    assert main(["registration-wave", command]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == ["cli_usage_error"]


def test_validate_intake_uses_exact_raw_host_item_bytes(tmp_path, capfd):
    request = write_json(tmp_path / "intake.json", candidate_bundle(1))

    assert main(["registration-wave", "validate-intake", str(request)]) == 0
    result = json.loads(capfd.readouterr().out)

    assert result["verified"] is True
    assert result["item_evidence_digest"] == item(1)["item_evidence_digest"]
    assert result["host_observation_digest"] == host(1)["observation_digest"]


def test_malformed_transport_input_is_exit_one(tmp_path, capfd):
    request = tmp_path / "duplicate.json"
    request.write_text('{"claim":{},"claim":{}}', encoding="utf-8")

    assert main(["registration-wave", "validate-intake", str(request)]) == 1
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "input_invalid_json"
    ]


def test_prepare_slot_emits_only_a_synthetic_verified_candidate(tmp_path, capfd):
    selected_context = context(tmp_path / "cli-prepare-context")
    request_value = candidate_bundle(1)
    request_value["context"] = context_value(selected_context)
    request = write_json(tmp_path / "prepare.json", request_value)

    assert main(["registration-wave", "prepare-slot", str(request)]) == 0
    result = json.loads(capfd.readouterr().out)

    assert result["schema"] == "sedb-ral.registration-wave-prepared-candidate/0.1"
    assert result["canonical_locator"] == claim(1)["desired_addresses"][0]["locator"]
    assert "continuity_merge" in result["not_claimed"]
    assert not selected_context.target_root.exists()


def test_build_plan_writes_only_explicit_output(tmp_path, capfd):
    selected_context = context(tmp_path / "cli-plan-context")
    candidates = make_candidates(tmp_path / "policy-candidates")
    request = write_json(
        tmp_path / "build-plan.json",
        {
            "context": context_value(selected_context),
            "candidates": [candidate_bundle(index) for index in (1, 2, 3)],
            "policy": policy(candidates).to_dict(),
            "registry_status": registry_status(),
            "checkpoint": checkpoint(),
        },
    )
    output = tmp_path / "plan.json"
    sentinel = write_json(tmp_path / "sentinel.json", {"unchanged": True})
    before = sentinel.read_bytes()

    assert (
        main(
            [
                "registration-wave",
                "build-plan",
                str(request),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    stdout = json.loads(capfd.readouterr().out)

    assert json.loads(output.read_text(encoding="utf-8")) == stdout
    assert [slot["slot_index"] for slot in stdout["ordered_slots"]] == [1, 2, 3]
    assert sentinel.read_bytes() == before
    assert not selected_context.target_root.exists()


def test_policy_plan_reverifies_three_principal_approvals(tmp_path, capfd):
    published = readback_published_storage.__wrapped__(tmp_path / "policy-storage")
    install_active_dormant(published)
    selected_context = context(tmp_path / "policy-plan-context")
    candidates = make_candidates(tmp_path / "policy-plan-candidates")
    selected_policy = policy(candidates)
    approvals = verified_approvals(tmp_path / "policy-plan-approvals", candidates)
    status = registry_root_status(storage=published)
    request = write_json(
        tmp_path / "policy-plan.json",
        {
            "context": context_value(selected_context),
            "candidates": [candidate_bundle(index) for index in (1, 2, 3)],
            "policy": selected_policy.to_dict(),
            "plan_registry_status": {
                "verified": True,
                "registry_control_digest": status["control_digest"],
                "registry_generation_digest": status["registry_generation_digest"],
                "ledger_head": None,
                "ledger_event_count": 0,
                "application_count": 0,
                "resident_count": 0,
                "address_count": 0,
            },
            "registry_status": status,
            "checkpoint": checkpoint(),
            "approvals": [approval_value(value) for value in approvals],
            "time": time_value(),
            "policy_time": policy_time_value(),
        },
    )

    assert main(["registration-wave", "policy-plan", str(request)]) == 0
    result = json.loads(capfd.readouterr().out)

    assert result["schema"] == "sedb-ral.registration-wave-policy-activation-request/0.1"
    assert result["application_approval_digests"] == [
        value.approval.digest for value in approvals
    ]


def test_slot_admit_without_synthetic_context_fails_before_request_io(
    tmp_path, capfd
):
    missing = tmp_path / "missing-request.json"

    assert main(["registration-wave", "slot-admit", str(missing)]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "production_wave_execution_not_authorized"
    ]


def test_slot_admit_runs_only_inside_the_explicit_synthetic_root(
    tmp_path, published_storage, capfd
):
    (
        selected_plan,
        selected_policy,
        approvals,
        policy_context,
        _candidate_value,
        slot_request,
        authorization,
    ) = setup_slot_one(tmp_path, published_storage)
    execution_context = engine_context(tmp_path / "cli-admit-execution")
    execution_context.target_root.mkdir()
    store_context = {
        **context_value(execution_context),
        "target_root": str(execution_context.target_root / "store"),
    }
    request = write_json(
        tmp_path / "slot-admit.json",
        {
            "context": context_value(context(tmp_path / "cli-admit-plan")),
            "candidates": [candidate_bundle(index) for index in (1, 2, 3)],
            "policy": selected_policy.to_dict(),
            "plan_registry_status": {
                "verified": True,
                "registry_control_digest": selected_plan.registry_control_digest,
                "registry_generation_digest": selected_plan.registry_generation_digest,
                "ledger_head": None,
                "ledger_event_count": 0,
                "application_count": 0,
                "resident_count": 0,
                "address_count": 0,
            },
            "checkpoint": checkpoint(),
            "approvals": [approval_value(value) for value in approvals],
            "time": time_value(),
            "policy_time": policy_time_value(),
            "slot_index": 1,
            "store_context": store_context,
            "store_root": str(execution_context.target_root / "store"),
            "execution_context": context_value(execution_context),
            "ledger_root": str(execution_context.target_root / "ledger"),
            "slot_request": slot_request.to_dict(),
            "execution_authorization": {
                "authorization": authorization.authorization.to_dict(),
                "raw_item": raw_principal_value(authorization.raw_item),
                "host": asdict(authorization.host),
                "expected_principal_ref": authorization.approval.approval.principal_ref,
            },
            "current_status": authorization.current_status,
            "policy_context": context_value(policy_context),
            "synthetic_storage_root": str(published_storage.parent.parent),
            "ctcl_receipt": CTCL,
            "staging_parent": str(execution_context.target_root / "staging-slot-1"),
        },
    )

    assert (
        main(
            [
                "registration-wave",
                "slot-admit",
                str(request),
                "--synthetic-root",
                str(execution_context.target_root),
            ]
        )
        == 0
    )
    result = json.loads(capfd.readouterr().out)

    assert result["execution_scope"] == "synthetic"
    assert result["production_wave_run"] == "NOT_RUN"
    assert result["live_limen_b6a"] == "NOT_RUN"
    assert len(result["appended_events"]) == 4


def test_export_readback_rebuilds_store_capabilities_not_plain_results(
    tmp_path, published_storage, capfd
):
    selected_context, selected_plan, ledger_root, capabilities = wave_state(
        tmp_path, published_storage, 1
    )
    store_context = {
        **context_value(selected_context),
        "target_root": str(selected_context.target_root / "store"),
    }
    request = write_json(
        tmp_path / "readback.json",
        {
            "context": context_value(selected_context),
            "store_context": store_context,
            "store_root": str(selected_context.target_root / "store"),
            "ledger_root": str(ledger_root),
            "expected_head": capabilities[0].result.post_head,
            "plan": selected_plan.to_dict(),
            "slot_result_ids": ["slot:1"],
        },
    )

    assert main(["registration-wave", "export-readback", str(request)]) == 0
    result = json.loads(capfd.readouterr().out)

    assert result["production_wave_run"] == "NOT_RUN"
    assert result["live_limen_b6a"] == "NOT_RUN"
    assert result["admitted_slot_indexes"] == [1]
