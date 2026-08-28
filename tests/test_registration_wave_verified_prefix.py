from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_registration_wave_contracts import (
    digest,
    valid_approval,
    valid_execution_authorization,
    valid_plan,
    valid_slot_request,
)

from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import append_event, read_verified_events
from sedb_ral.operations.models import OperationReceipt
from sedb_ral.registrar import RegistrarCommitReceipt
from sedb_ral.registration_wave_models import (
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    SlotExecutionAuthorization,
    WaveSlotReceipt,
    WaveSlotRequest,
)
from sedb_ral.registration_wave_plan import (
    VerifiedWaveReceiptPrefix,
    WaveReceiptEvidence,
    build_slot_request,
    derive_next_slot,
    verify_wave_receipt_prefix,
)

CTCL = json.loads(
    (Path(__file__).parents[1] / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)


def event_draft() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "event_id": "evt_001",
        "ledger_id": "ledger:test",
        "event_type": "identifier.observed",
        "causal_parent_ids": [],
        "recorded_time_ref": "ctcl:instant:5a76bd1b-2db2-463b-b2ad-0b1307102710",
        "recorded_time": "2026-08-23T08:09:39.165Z",
        "payload": {"identifier_id": "id:test"},
    }


def plan() -> RegistrationWavePlan:
    return RegistrationWavePlan.from_dict(valid_plan())


def request(selected_plan: RegistrationWavePlan) -> WaveSlotRequest:
    value = valid_slot_request()
    slot = selected_plan.ordered_slots[0]
    value.update(
        {
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": slot["slot_id"],
            "candidate_ref": slot["candidate_ref"],
            "candidate_digest": slot["candidate_digest"],
            "application_ref": slot["application_ref"],
            "application_digest": slot["application_digest"],
            "policy_ref": selected_plan.policy_ref,
            "policy_digest": selected_plan.policy_digest,
            "checkpoint_ref": selected_plan.checkpoint_ref,
            "checkpoint_digest": selected_plan.checkpoint_digest,
            "registry_generation_digest": selected_plan.registry_generation_digest,
            "registry_control_digest": selected_plan.registry_control_digest,
        }
    )
    return WaveSlotRequest.sealed(value)


def approval(selected_plan: RegistrationWavePlan) -> PrincipalApplicationApproval:
    value = valid_approval()
    value["application_ref"] = selected_plan.ordered_slots[0]["application_ref"]
    value["application_digest"] = selected_plan.ordered_slots[0][
        "application_digest"
    ]
    return PrincipalApplicationApproval.sealed(value)


def authorization(
    selected_plan: RegistrationWavePlan,
    selected_request: WaveSlotRequest,
    selected_approval: PrincipalApplicationApproval,
) -> SlotExecutionAuthorization:
    value = valid_execution_authorization()
    value.update(
        {
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": selected_plan.ordered_slots[0]["slot_id"],
            "operation_request_ref": selected_request.request_id,
            "operation_request_digest": selected_request.digest,
            "application_approval_ref": selected_approval.approval_id,
            "application_approval_digest": selected_approval.digest,
            "policy_ref": selected_plan.policy_ref,
            "policy_digest": selected_plan.policy_digest,
            "checkpoint_ref": selected_plan.checkpoint_ref,
            "checkpoint_digest": selected_plan.checkpoint_digest,
            "registry_control_digest": selected_plan.registry_control_digest,
        }
    )
    return SlotExecutionAuthorization.sealed(value)


def operation_receipt(
    selected_plan: RegistrationWavePlan,
    selected_request: WaveSlotRequest,
    core: RegistrarCommitReceipt,
) -> OperationReceipt:
    material = {
        "schema": "sedb-ral.registrar-operation-receipt/0.1",
        "operation_id": "operation:slot-1",
        "request_digest": selected_request.digest,
        "policy_digest": selected_plan.policy_digest,
        "operations_generation": "operations-generation:synthetic",
        "registry_id": "registry:synthetic",
        "pre_head": core.source_head,
        "post_head": core.final_head,
        "outcome": "complete",
        "registrar_receipt_ref": "registrar-commit-receipt:slot-1",
        "registrar_receipt_digest": sha256_ref(core.to_dict()),
        "projection_ref": "projection:slot-1",
        "projection_digest": core.projection_digest,
        "error_codes": [],
        "side_effect_counters": {
            "synthetic_registry_writes": 1,
            "production_registry_writes": 0,
            "private_reads": 0,
            "network_calls": 0,
            "external_sends": 0,
            "fabric_events": 0,
        },
        "completed_time_ref": "ctcl:instant:operation-complete",
        "not_claimed": ["production_execution", "private_access"],
    }
    material["receipt_digest"] = sha256_ref(material)
    return OperationReceipt.from_dict(material)


def exact_evidence(tmp_path: Path) -> tuple[RegistrationWavePlan, WaveReceiptEvidence]:
    selected_plan = plan()
    selected_request = request(selected_plan)
    selected_approval = approval(selected_plan)
    selected_authorization = authorization(
        selected_plan, selected_request, selected_approval
    )
    append = append_event(
        tmp_path,
        event_draft(),
        CTCL,
        expected_previous_chain_digest=None,
    )
    events = read_verified_events(tmp_path, append.chain_digest)
    core = RegistrarCommitReceipt(
        application_digest=selected_plan.ordered_slots[0]["application_digest"],
        prepared_digest=digest("prepared-1"),
        source_head=None,
        final_head=append.chain_digest,
        event_ids=("evt_001",),
        projection_digest=digest("core-projection-1"),
        committed=True,
        idempotent=False,
    )
    operation = operation_receipt(selected_plan, selected_request, core)
    selected_receipt = WaveSlotReceipt.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-receipt/0.1",
            "receipt_id": "slot-receipt:1",
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": selected_plan.ordered_slots[0]["slot_id"],
            "slot_index": 1,
            "slot_request_ref": selected_request.request_id,
            "slot_request_digest": selected_request.digest,
            "execution_authorization_ref": selected_authorization.execution_authorization_id,
            "execution_authorization_digest": selected_authorization.digest,
            "application_approval_ref": selected_approval.approval_id,
            "application_approval_digest": selected_approval.digest,
            "pre_head": None,
            "post_head": append.chain_digest,
            "appended_events": [
                {
                    "event_ref": events[0]["event_id"],
                    "event_digest": sha256_ref(events[0]),
                }
            ],
            "projection_digests": {
                "application": digest("application-projection-1"),
                "resident": digest("resident-projection-1"),
                "instance": digest("instance-projection-1"),
                "address": digest("address-projection-1"),
                "binding": digest("binding-projection-1"),
            },
            "commit_receipt_ref": "registrar-commit-receipt:slot-1",
            "commit_receipt_digest": sha256_ref(core.to_dict()),
            "operation_receipt_ref": "registrar-operation-receipt:operation:slot-1",
            "operation_receipt_digest": operation.digest,
            "event_count_delta": 1,
            "limen_b6a_status": "current",
            "limen_b6a_result_ref": "limen-result:1",
            "limen_b6a_result_digest": digest("limen-result-1"),
            "effect_deltas": {
                "resident": 1,
                "application": 1,
                "address": 1,
                "private": 0,
                "network": 0,
                "external": 0,
            },
            "status": "accepted",
            "not_claimed": ["rank", "private_access"],
        }
    )
    return selected_plan, WaveReceiptEvidence(
        receipt=selected_receipt,
        slot_request=selected_request,
        execution_authorization=selected_authorization,
        application_approval=selected_approval,
        registrar_commit_receipt=core,
        operation_receipt=operation,
        ledger_root=tmp_path,
    )


def test_raw_self_sealed_receipt_and_matching_caller_event_cannot_advance():
    selected_plan = plan()
    fabricated_event = {
        "event_ref": "event:fabricated",
        "event_digest": digest("fabricated-event"),
    }
    value = exact_receipt_shape(selected_plan, fabricated_event)
    fabricated_receipt = WaveSlotReceipt.sealed(value)

    with pytest.raises(RALValidationError, match="verified_receipt_prefix_required"):
        derive_next_slot(selected_plan, (fabricated_receipt,), (fabricated_event,))


def exact_receipt_shape(
    selected_plan: RegistrationWavePlan, event_pair: dict[str, object]
) -> dict[str, object]:
    value = {
        "schema": "sedb-ral.registration-wave-slot-receipt/0.1",
        "receipt_id": "slot-receipt:fabricated",
        "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
        "wave_plan_digest": selected_plan.digest,
        "slot_id": selected_plan.ordered_slots[0]["slot_id"],
        "slot_index": 1,
        "slot_request_ref": "slot-request:fabricated",
        "slot_request_digest": digest("slot-request-fabricated"),
        "execution_authorization_ref": "execution-authorization:fabricated",
        "execution_authorization_digest": digest("execution-fabricated"),
        "application_approval_ref": "approval:fabricated",
        "application_approval_digest": digest("approval-fabricated"),
        "pre_head": None,
        "post_head": digest("fabricated-head"),
        "appended_events": [event_pair],
        "projection_digests": {
            name: digest(f"{name}-fabricated")
            for name in ("application", "resident", "instance", "address", "binding")
        },
        "commit_receipt_ref": "commit:fabricated",
        "commit_receipt_digest": digest("commit-fabricated"),
        "operation_receipt_ref": "operation:fabricated",
        "operation_receipt_digest": digest("operation-fabricated"),
        "event_count_delta": 1,
        "limen_b6a_status": "current",
        "limen_b6a_result_ref": "limen:fabricated",
        "limen_b6a_result_digest": digest("limen-fabricated"),
        "effect_deltas": {
            "resident": 1,
            "application": 1,
            "address": 1,
            "private": 0,
            "network": 0,
            "external": 0,
        },
        "status": "accepted",
        "not_claimed": ["rank"],
    }
    return value


def test_exact_evidence_produces_capability_and_advances_one_slot(tmp_path):
    selected_plan, evidence = exact_evidence(tmp_path)

    prefix = verify_wave_receipt_prefix(selected_plan, (evidence,))

    assert isinstance(prefix, VerifiedWaveReceiptPrefix)
    assert derive_next_slot(selected_plan, prefix).slot_index == 2
    request_two = build_slot_request(
        selected_plan,
        2,
        prefix,
        {
            "expected_ledger_head": evidence.receipt.post_head,
            "cli_token": evidence.receipt.post_head,
            "ledger_event_count": 1,
        },
    )
    assert request_two.predecessor_receipt_digest == evidence.receipt.digest


def test_changed_receipt_request_binding_fails_capability_creation(tmp_path):
    selected_plan, evidence = exact_evidence(tmp_path)
    changed = evidence.receipt.to_dict()
    changed["slot_request_digest"] = digest("another-request")
    changed_receipt = WaveSlotReceipt.sealed(changed)
    changed_evidence = WaveReceiptEvidence(
        receipt=changed_receipt,
        slot_request=evidence.slot_request,
        execution_authorization=evidence.execution_authorization,
        application_approval=evidence.application_approval,
        registrar_commit_receipt=evidence.registrar_commit_receipt,
        operation_receipt=evidence.operation_receipt,
        ledger_root=evidence.ledger_root,
    )

    with pytest.raises(RALValidationError, match="wave_receipt_evidence_mismatch"):
        verify_wave_receipt_prefix(selected_plan, (changed_evidence,))


def test_empty_verified_prefix_is_required_for_slot_one():
    selected_plan = plan()
    prefix = verify_wave_receipt_prefix(selected_plan, ())

    request_one = build_slot_request(
        selected_plan,
        1,
        prefix,
        {
            "expected_ledger_head": None,
            "cli_token": "GENESIS",
            "ledger_event_count": 0,
        },
    )

    assert request_one.slot_index == 1
