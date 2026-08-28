from __future__ import annotations

import copy

import pytest

from sedb_ral.canonical import sha256_ref
from sedb_ral.contracts import load_schema
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_models import (
    ActiveWavePolicyRecord,
    ApplicantItemEvidence,
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    RegistrationWavePolicy,
    RegistrationWavePreparedCandidate,
    SlotExecutionAuthorization,
    SyntheticWaveSlotExecutionResult,
    SyntheticWaveSlotRecoveryResult,
    WaveHostObservation,
    WavePolicyActivationAuthority,
    WavePolicyActivationReceipt,
    WavePolicyActivationRequest,
    WaveReadbackBundle,
    WaveSlot,
    WaveSlotReceipt,
    WaveSlotRecoveryAuthorization,
    WaveSlotRecoveryReceipt,
    WaveSlotRequest,
    WaveTerminalEvent,
)

DIGEST_PREFIX = "sha256:sedb-ral-json-nfc-codepoint-v1:"
THREADS = (
    "10000000-0000-4000-8000-000000000001",
    "20000000-0000-4000-8000-000000000002",
    "30000000-0000-4000-8000-000000000003",
)


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def seal(material: dict[str, object], field: str) -> dict[str, object]:
    value = copy.deepcopy(material)
    value[field] = sha256_ref(value)
    return value


def valid_item() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-applicant-item-evidence/0.1",
            "item_evidence_id": "item-evidence:slot-1",
            "provider": "openai",
            "adapter_kind": "codex_app_task_tool",
            "native_thread_id": THREADS[0],
            "native_turn_id": "turn:slot-1",
            "source_item_role": "assistant",
            "source_item_kind": "agentMessage",
            "source_item_status": "completed",
            "source_item_parent_thread_id": THREADS[0],
            "source_item_parent_turn_id": "turn:slot-1",
            "applicant_item_ref": "item:slot-1",
            "canonical_claim_digest": digest("claim-1"),
            "raw_item_evidence_digest": digest("raw-item-1"),
            "capture_status": "host_observed",
            "observed_origin": "host:codex-app",
            "observed_at_ref": "ctcl:instant:slot-1",
            "unavailable_fields": [
                {
                    "field": "native_session_id",
                    "reason": "structurally_unavailable_from_codex_app_task_tool",
                }
            ],
            "not_claimed": ["verified_identity", "registrar_authority"],
        },
        "item_evidence_digest",
    )


def valid_host() -> dict[str, object]:
    item = valid_item()
    return seal(
        {
            "schema": "sedb-ral.registration-host-observation/0.2",
            "observation_id": "observation:slot-1",
            "provider": "openai",
            "adapter_kind": "codex_app_task_tool",
            "identifier_kind": "codex_thread",
            "native_thread_id": THREADS[0],
            "native_session_id": None,
            "native_turn_id": "turn:slot-1",
            "unavailable_fields": item["unavailable_fields"],
            "observed_origin": "host:codex-app",
            "observed_at_ref": "ctcl:instant:slot-1",
            "applicant_item_ref": "item:slot-1",
            "applicant_item_evidence_ref": "item-evidence:slot-1",
            "applicant_item_evidence_digest": item["item_evidence_digest"],
            "canonical_claim_digest": digest("claim-1"),
            "not_claimed": ["pre_turn_output_enforcement", "verified_identity"],
        },
        "observation_digest",
    )


def valid_candidate(index: int = 1) -> dict[str, object]:
    host = valid_host()
    item = valid_item()
    return seal(
        {
            "schema": "sedb-ral.registration-wave-prepared-candidate/0.1",
            "candidate_id": f"candidate:slot-{index}",
            "claim_ref": f"claim:slot-{index}",
            "canonical_claim_digest": digest(f"claim-{index}"),
            "item_evidence_ref": f"item-evidence:slot-{index}",
            "item_evidence_digest": (
                item["item_evidence_digest"] if index == 1 else digest(f"item-{index}")
            ),
            "host_v02_ref": f"observation:slot-{index}",
            "host_v02_digest": (
                host["observation_digest"] if index == 1 else digest(f"host-{index}")
            ),
            "compatibility_host_v01_ref": f"host-v01:slot-{index}",
            "compatibility_host_v01_digest": digest(f"host-v01-{index}"),
            "prepared_registration_ref": f"prepared:slot-{index}",
            "prepared_registration_digest": digest(f"prepared-{index}"),
            "application_ref": f"application:slot-{index}",
            "application_digest": digest(f"application-{index}"),
            "canonical_locator": THREADS[index - 1],
            "not_claimed": ["verified_identity", "private_access"],
        },
        "candidate_digest",
    )


def valid_slots() -> list[dict[str, object]]:
    slots = []
    for index in (1, 2, 3):
        candidate = valid_candidate(index)
        slots.append(
            {
                "slot_id": f"slot:{index}",
                "slot_index": index,
                "candidate_ref": candidate["candidate_id"],
                "candidate_digest": candidate["candidate_digest"],
                "application_ref": candidate["application_ref"],
                "application_digest": candidate["application_digest"],
                "host_observation_ref": candidate["host_v02_ref"],
                "host_observation_digest": candidate["host_v02_digest"],
            }
        )
    return slots


def valid_plan() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-plan/0.1",
            "wave_id": "wave:synthetic:1",
            "ordered_slots": valid_slots(),
            "initial_ledger_state": {
                "expected_ledger_head": None,
                "cli_token": "GENESIS",
                "ledger_event_count": 0,
            },
            "registry_control_digest": digest("registry-control"),
            "registry_generation_digest": digest("registry-generation"),
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "terminal_boundary": "after_slot_3_or_stop",
            "not_claimed": ["rank", "seniority", "continuity"],
        },
        "wave_plan_digest",
    )


def valid_policy() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-policy/0.1",
            "policy_id": "policy:wave-1",
            "wave_id": "wave:synthetic:1",
            "ordered_application_digests": [
                digest("application-1"),
                digest("application-2"),
                digest("application-3"),
            ],
            "ordered_locators": list(THREADS),
            "allowed_actions": ["prepare", "readback", "admit_one"],
            "max_slots": 3,
            "batch_append": False,
            "capabilities": {
                "correction": False,
                "merge": False,
                "private_access": False,
                "network_send": False,
                "provider_call": False,
                "fabric_emit": False,
                "mcp_call": False,
                "cloud": False,
                "deletion": False,
            },
            "valid_from_ref": "ctcl:instant:policy-start",
            "expires_at_ref": "ctcl:instant:policy-end",
            "not_claimed": ["batch_authority", "private_access"],
        },
        "policy_digest",
    )


def valid_active_policy_record() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-active-policy-record/0.1",
            "record_id": "active-policy:1",
            "sequence": 1,
            "predecessor_record_ref": "active-policy:0",
            "predecessor_record_digest": digest("active-policy-0"),
            "dormant_policy_digest": digest("dormant-policy"),
            "wave_policy_ref": "policy:wave-1",
            "wave_policy_digest": digest("policy"),
            "registry_generation_digest": digest("registry-generation"),
            "extension_index_digest": digest("extension-index"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "activation_authority_ref": "authority:policy-activation",
            "activation_authority_digest": digest("activation-authority"),
            "activation_request_ref": "request:policy-activation",
            "activation_request_digest": digest("activation-request"),
            "status": "active",
            "valid_until_ref": "ctcl:instant:policy-end",
            "not_claimed": ["resident_registration"],
        },
        "record_digest",
    )


def valid_activation_request() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-request/0.1",
            "request_id": "request:policy-activation",
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "application_approval_digests": [
                digest("approval-1"),
                digest("approval-2"),
                digest("approval-3"),
            ],
            "expected_predecessor_record_ref": "active-policy:0",
            "expected_predecessor_record_digest": digest("active-policy-0"),
            "registry_generation_digest": digest("registry-generation"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "requested_at_ref": "ctcl:instant:activation-request",
            "not_claimed": ["ledger_append", "resident_registration"],
        },
        "request_digest",
    )


def valid_activation_authority() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-authority/0.1",
            "authority_id": "authority:policy-activation",
            "principal_ref": "principal:neo-k",
            "operation": "registration.wave-policy.activate",
            "request_ref": "request:policy-activation",
            "request_digest": digest("activation-request"),
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "target_ref": "registrar-operations:production",
            "valid_from_ref": "ctcl:instant:authority-start",
            "expires_at_ref": "ctcl:instant:authority-end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": "user-item:activation",
            "source_user_item_digest": digest("user-item-activation"),
            "host_observation_ref": "host-observation:activation",
            "host_observation_digest": digest("host-observation-activation"),
            "not_claimed": ["resident_registration", "private_access"],
        },
        "authority_digest",
    )


def valid_activation_receipt() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-receipt/0.1",
            "receipt_id": "receipt:policy-activation:1",
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "active_policy_ref": "active-policy:1",
            "active_policy_digest": digest("active-policy-1"),
            "predecessor_record_ref": "active-policy:0",
            "predecessor_record_digest": digest("active-policy-0"),
            "registry_generation_digest": digest("registry-generation"),
            "extension_index_digest": digest("extension-index"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "authority_ref": "authority:policy-activation",
            "authority_digest": digest("activation-authority"),
            "request_ref": "request:policy-activation",
            "request_digest": digest("activation-request"),
            "application_approval_digests": [
                digest("approval-1"),
                digest("approval-2"),
                digest("approval-3"),
            ],
            "acl_observation_ref": "acl-observation:1",
            "acl_observation_digest": digest("acl-observation"),
            "pre_status_digest": digest("pre-status"),
            "post_status_digest": digest("post-status"),
            "status": "activated",
            "observed_at_ref": "ctcl:instant:activation-receipt",
            "not_claimed": ["resident_registration", "private_access"],
        },
        "receipt_digest",
    )


def valid_approval() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.principal-application-approval/0.1",
            "approval_id": "approval:slot-1",
            "principal_ref": "principal:neo-k",
            "application_ref": "application:slot-1",
            "application_digest": digest("application-1"),
            "source_user_item_ref": "user-item:approval-1",
            "source_user_item_digest": digest("user-item-approval-1"),
            "host_observation_ref": "host-observation:approval-1",
            "host_observation_digest": digest("host-observation-approval-1"),
            "approved_scopes": ["registration.application.approve"],
            "valid_from_ref": "ctcl:instant:approval-start",
            "expires_at_ref": "ctcl:instant:approval-end",
            "status": "active",
            "revoked_by_ref": None,
            "not_claimed": ["slot_execution", "registrar_authority"],
        },
        "approval_digest",
    )


def valid_execution_authorization() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-slot-execution-authorization/0.1",
            "execution_authorization_id": "execution-authorization:slot-1",
            "principal_ref": "principal:neo-k",
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "slot_id": "slot:1",
            "slot_index": 1,
            "operation_request_ref": "operation-request:slot-1",
            "operation_request_digest": digest("operation-request-1"),
            "application_approval_ref": "approval:slot-1",
            "application_approval_digest": digest("approval-1"),
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "expected_ledger_head": None,
            "registry_control_digest": digest("registry-control"),
            "valid_from_ref": "ctcl:instant:execution-start",
            "expires_at_ref": "ctcl:instant:execution-end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": "user-item:execution-1",
            "source_user_item_digest": digest("user-item-execution-1"),
            "host_observation_ref": "host-observation:execution-1",
            "host_observation_digest": digest("host-observation-execution-1"),
            "not_claimed": ["batch_execution", "private_access"],
        },
        "execution_authorization_digest",
    )


def valid_slot_request() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-slot-request/0.1",
            "request_id": "slot-request:1",
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "slot_id": "slot:1",
            "slot_index": 1,
            "candidate_ref": "candidate:slot-1",
            "candidate_digest": digest("candidate-1"),
            "application_ref": "application:slot-1",
            "application_digest": digest("application-1"),
            "predecessor_receipt_ref": None,
            "predecessor_receipt_digest": None,
            "expected_ledger_state": {
                "expected_ledger_head": None,
                "cli_token": "GENESIS",
                "ledger_event_count": 0,
            },
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "registry_generation_digest": digest("registry-generation"),
            "registry_control_digest": digest("registry-control"),
            "not_claimed": ["batch_execution", "rank"],
        },
        "request_digest",
    )


def result_material(schema: str) -> dict[str, object]:
    return {
        "schema": schema,
        "result_id": "slot-result:1",
        "wave_plan_ref": "wave-plan:1",
        "wave_plan_digest": digest("wave-plan"),
        "slot_id": "slot:1",
        "slot_index": 1,
        "slot_request_ref": "slot-request:1",
        "slot_request_digest": digest("slot-request-1"),
        "execution_authorization_ref": "execution-authorization:slot-1",
        "execution_authorization_digest": digest("execution-authorization-1"),
        "application_approval_ref": "approval:slot-1",
        "application_approval_digest": digest("approval-1"),
        "pre_head": None,
        "post_head": digest("head-1"),
        "appended_events": [
            {"event_ref": "event:slot-1:1", "event_digest": digest("event-1")}
        ],
        "projection_digests": {
            "application": digest("projection-application"),
            "resident": digest("projection-resident"),
            "instance": digest("projection-instance"),
            "address": digest("projection-address"),
            "binding": digest("projection-binding"),
        },
        "execution_scope": "synthetic",
        "production_wave_run": "NOT_RUN",
        "live_limen_b6a": "NOT_RUN",
        "not_claimed": ["production_admission", "live_limen_resolution"],
    }


def valid_synthetic_result() -> dict[str, object]:
    return seal(
        result_material("sedb-ral.synthetic-wave-slot-execution-result/0.1"),
        "result_digest",
    )


def valid_slot_receipt() -> dict[str, object]:
    material = result_material("sedb-ral.registration-wave-slot-receipt/0.1")
    material.pop("result_id")
    material.pop("execution_scope")
    material.pop("production_wave_run")
    material.pop("live_limen_b6a")
    material.update(
        {
            "receipt_id": "slot-receipt:1",
            "commit_receipt_ref": "commit-receipt:1",
            "commit_receipt_digest": digest("commit-receipt-1"),
            "operation_receipt_ref": "operation-receipt:1",
            "operation_receipt_digest": digest("operation-receipt-1"),
            "event_count_delta": 1,
            "limen_b6a_status": "pending",
            "limen_b6a_result_ref": None,
            "limen_b6a_result_digest": None,
            "effect_deltas": {
                "resident": 1,
                "application": 1,
                "address": 1,
                "private": 0,
                "network": 0,
                "external": 0,
            },
            "status": "canonical_committed_readback_failed",
        }
    )
    return seal(material, "receipt_digest")


def valid_recovery_authorization() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-slot-recovery-authorization/0.1",
            "recovery_authorization_id": "recovery-authorization:slot-1",
            "principal_ref": "principal:neo-k",
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "slot_id": "slot:1",
            "slot_request_ref": "slot-request:1",
            "slot_request_digest": digest("slot-request-1"),
            "original_execution_authorization_ref": "execution-authorization:slot-1",
            "original_execution_authorization_digest": digest("execution-authorization-1"),
            "application_approval_ref": "approval:slot-1",
            "application_approval_digest": digest("approval-1"),
            "verified_prefix_digest": digest("verified-prefix"),
            "pre_head": None,
            "post_head": digest("head-1"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "current_readback_digest": digest("current-readback"),
            "valid_from_ref": "ctcl:instant:recovery-start",
            "expires_at_ref": "ctcl:instant:recovery-end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": "user-item:recovery-1",
            "source_user_item_digest": digest("user-item-recovery-1"),
            "host_observation_ref": "host-observation:recovery-1",
            "host_observation_digest": digest("host-observation-recovery-1"),
            "not_claimed": ["new_admission", "partial_prefix_acceptance"],
        },
        "recovery_authorization_digest",
    )


def valid_synthetic_recovery_result() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.synthetic-wave-slot-recovery-result/0.1",
            "result_id": "synthetic-recovery-result:1",
            "recovery_authorization_ref": "recovery-authorization:slot-1",
            "recovery_authorization_digest": digest("recovery-authorization-1"),
            "verified_prefix_digest": digest("verified-prefix"),
            "pre_head": None,
            "post_head": digest("head-1"),
            "reconstructed_result_ref": "slot-result:1",
            "reconstructed_result_digest": digest("slot-result-1"),
            "execution_scope": "synthetic",
            "production_wave_run": "NOT_RUN",
            "live_limen_b6a": "NOT_RUN",
            "status": "recovered_synthetic",
            "not_claimed": ["production_recovery", "accepted_admission"],
        },
        "result_digest",
    )


def valid_recovery_receipt() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-slot-recovery-receipt/0.1",
            "receipt_id": "recovery-receipt:1",
            "recovery_authorization_ref": "recovery-authorization:slot-1",
            "recovery_authorization_digest": digest("recovery-authorization-1"),
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "slot_id": "slot:1",
            "application_digest": digest("application-1"),
            "original_execution_authorization_ref": "execution-authorization:slot-1",
            "original_execution_authorization_digest": digest("execution-authorization-1"),
            "verified_prefix_digest": digest("verified-prefix"),
            "pre_head": None,
            "post_head": digest("head-1"),
            "checkpoint_ref": "checkpoint:wave-1",
            "checkpoint_digest": digest("checkpoint"),
            "current_readback_digest": digest("current-readback"),
            "reconstructed_receipt_ref": "slot-receipt:1",
            "reconstructed_receipt_digest": digest("slot-receipt-1"),
            "status": "recovered",
            "not_claimed": ["partial_prefix_acceptance"],
        },
        "receipt_digest",
    )


def valid_terminal_event() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-terminal-event/0.1",
            "event_id": "wave-terminal:1",
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "policy_ref": "policy:wave-1",
            "policy_digest": digest("policy"),
            "previous_record_ref": "active-policy:1",
            "previous_record_digest": digest("active-policy-1"),
            "terminal_status": "stopped",
            "reason_code": "operator_stop",
            "created_time_ref": "ctcl:instant:terminal",
            "authority_ref": "authority:terminal",
            "authority_digest": digest("terminal-authority"),
            "not_claimed": ["rollback", "deletion"],
        },
        "event_digest",
    )


def valid_readback_bundle() -> dict[str, object]:
    return seal(
        {
            "schema": "sedb-ral.registration-wave-readback-bundle/0.1",
            "bundle_id": "readback-bundle:1",
            "wave_plan_ref": "wave-plan:1",
            "wave_plan_digest": digest("wave-plan"),
            "expected_ledger_head": digest("head-1"),
            "admitted_slot_indexes": [1],
            "ral_view_schema_id": "https://evemisslab.com/schemas/limen/ral-view-v0.2.json",
            "raw_sha256": "1" * 64,
            "public_view_digest": digest("public-view"),
            "ledger_head": digest("head-1"),
            "binding_head": digest("binding-head"),
            "authority_head": digest("authority-head"),
            "source_events": [
                {"event_ref": "event:slot-1:1", "event_digest": digest("event-1")}
            ],
            "slot_projection_digests": [
                {
                    "slot_index": 1,
                    "application": digest("projection-application"),
                    "resident": digest("projection-resident"),
                    "instance": digest("projection-instance"),
                    "address": digest("projection-address"),
                    "binding": digest("projection-binding"),
                }
            ],
            "production_wave_run": "NOT_RUN",
            "live_limen_b6a": "NOT_RUN",
            "not_claimed": ["live_limen_resolution", "private_access"],
        },
        "bundle_digest",
    )


CASES = (
    (ApplicantItemEvidence, valid_item, "item_evidence_digest"),
    (WaveHostObservation, valid_host, "observation_digest"),
    (RegistrationWavePreparedCandidate, valid_candidate, "candidate_digest"),
    (RegistrationWavePlan, valid_plan, "wave_plan_digest"),
    (RegistrationWavePolicy, valid_policy, "policy_digest"),
    (ActiveWavePolicyRecord, valid_active_policy_record, "record_digest"),
    (WavePolicyActivationRequest, valid_activation_request, "request_digest"),
    (WavePolicyActivationAuthority, valid_activation_authority, "authority_digest"),
    (WavePolicyActivationReceipt, valid_activation_receipt, "receipt_digest"),
    (PrincipalApplicationApproval, valid_approval, "approval_digest"),
    (
        SlotExecutionAuthorization,
        valid_execution_authorization,
        "execution_authorization_digest",
    ),
    (WaveSlotRequest, valid_slot_request, "request_digest"),
    (SyntheticWaveSlotExecutionResult, valid_synthetic_result, "result_digest"),
    (WaveSlotReceipt, valid_slot_receipt, "receipt_digest"),
    (
        WaveSlotRecoveryAuthorization,
        valid_recovery_authorization,
        "recovery_authorization_digest",
    ),
    (
        SyntheticWaveSlotRecoveryResult,
        valid_synthetic_recovery_result,
        "result_digest",
    ),
    (WaveSlotRecoveryReceipt, valid_recovery_receipt, "receipt_digest"),
    (WaveTerminalEvent, valid_terminal_event, "event_digest"),
    (WaveReadbackBundle, valid_readback_bundle, "bundle_digest"),
)


@pytest.mark.parametrize(("contract", "factory", "digest_field"), CASES)
def test_wave_contract_round_trips_and_verifies(contract, factory, digest_field):
    value = factory()
    parsed = contract.from_dict(value)

    assert parsed.to_dict() == value
    assert parsed.digest == value[digest_field]
    assert parsed.verify() is None


def test_wave_slot_round_trips_without_rank_or_authority_fields():
    value = valid_slots()[0]
    parsed = WaveSlot.from_dict(value)

    assert parsed.to_dict() == value
    assert parsed.slot_index == 1
    assert parsed.verify() is None


def test_sealed_computes_the_domain_separated_digest_once():
    material = valid_item()
    material.pop("item_evidence_digest")

    parsed = ApplicantItemEvidence.sealed(material)

    assert parsed.digest == sha256_ref(material)
    assert parsed.source_item_kind == "agentMessage"


@pytest.mark.parametrize(("contract", "factory", "digest_field"), CASES)
def test_wave_schema_asset_is_strict_and_has_stable_id(
    contract, factory, digest_field
):
    schema = load_schema(contract.schema_name)

    assert schema["$id"] == (
        "https://evemisslab.com/schemas/sedb-ral/" + contract.schema_name
    )
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(("contract", "factory", "digest_field"), CASES)
def test_wave_contract_rejects_unknown_field_after_valid_reseal(
    contract, factory, digest_field
):
    value = factory()
    value.pop(digest_field)
    value["unexpected"] = True
    value = seal(value, digest_field)

    with pytest.raises(RALValidationError, match="schema_invalid"):
        contract.from_dict(value)


@pytest.mark.parametrize(("contract", "factory", "digest_field"), CASES)
def test_wave_contract_rejects_stale_digest(contract, factory, digest_field):
    value = factory()
    value["not_claimed"] = ["changed"]

    with pytest.raises(RALValidationError, match="digest_mismatch"):
        contract.from_dict(value)


@pytest.mark.parametrize(
    ("role", "kind", "status"),
    (
        ("user", "agentMessage", "completed"),
        ("assistant", "toolCall", "completed"),
        ("assistant", "agentMessage", "inProgress"),
    ),
)
def test_applicant_item_evidence_rejects_noncanonical_output(role, kind, status):
    value = valid_item()
    value.pop("item_evidence_digest")
    value.update(
        {
            "source_item_role": role,
            "source_item_kind": kind,
            "source_item_status": status,
        }
    )
    value = seal(value, "item_evidence_digest")

    with pytest.raises(RALValidationError, match="applicant_item_role_invalid"):
        ApplicantItemEvidence.from_dict(value)


def test_applicant_item_evidence_rejects_parent_mismatch():
    value = valid_item()
    value.pop("item_evidence_digest")
    value["source_item_parent_turn_id"] = "turn:other"
    value = seal(value, "item_evidence_digest")

    with pytest.raises(RALValidationError, match="applicant_item_parent_mismatch"):
        ApplicantItemEvidence.from_dict(value)


@pytest.mark.parametrize("mutation", ("duplicate", "reorder", "rank"))
def test_wave_plan_requires_three_contiguous_equal_standing_slots(mutation):
    value = valid_plan()
    value.pop("wave_plan_digest")
    slots = copy.deepcopy(value["ordered_slots"])
    if mutation == "duplicate":
        slots[2] = copy.deepcopy(slots[1])
    elif mutation == "reorder":
        slots[0], slots[1] = slots[1], slots[0]
    else:
        slots[0]["rank"] = 1
    value["ordered_slots"] = slots
    value = seal(value, "wave_plan_digest")

    with pytest.raises(RALValidationError):
        RegistrationWavePlan.from_dict(value)


def test_synthetic_result_rejects_production_receipt_shape():
    value = valid_slot_receipt()
    value.pop("receipt_digest")
    value["result_digest"] = sha256_ref(value)
    with pytest.raises(RALValidationError, match="schema_invalid"):
        SyntheticWaveSlotExecutionResult.from_dict(value)


def test_contract_digest_uses_domain_separated_profile():
    assert all(factory()[field].startswith(DIGEST_PREFIX) for _, factory, field in CASES)
