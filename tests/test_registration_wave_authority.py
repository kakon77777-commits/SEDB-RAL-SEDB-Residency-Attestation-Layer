from __future__ import annotations

from dataclasses import replace

import pytest
from test_registration_wave_plan import candidates, checkpoint, plan, policy

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_authority import (
    AuthorityTimeEvidence,
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedApplicationApproval,
    VerifiedAuthorityTimeEvidence,
    VerifiedSlotExecutionAuthorization,
    verify_application_approval,
    verify_authority_time_evidence,
    verify_slot_execution_authorization,
)
from sedb_ral.registration_wave_models import (
    PrincipalApplicationApproval,
    SlotExecutionAuthorization,
)
from sedb_ral.registration_wave_plan import (
    build_slot_request,
    verify_wave_receipt_prefix,
)

PRINCIPAL_REF = "principal:synthetic-wave-authority"
PRINCIPAL_THREAD = "90000000-0000-4000-8000-000000000009"


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def raw_time_evidence(
    *, now: int = 200, valid_from: int = 100, expires_at: int | None = 300
) -> AuthorityTimeEvidence:
    return AuthorityTimeEvidence(
        now_ref="time:now",
        now_epoch_ns=now,
        valid_from_ref="time:start",
        valid_from_epoch_ns=valid_from,
        expires_at_ref=None if expires_at is None else "time:end",
        expires_at_epoch_ns=expires_at,
        source_ref="clock:synthetic",
        source_digest=digest("clock-source"),
    )


def time_evidence(
    *, now: int = 200, valid_from: int = 100, expires_at: int | None = 300
) -> VerifiedAuthorityTimeEvidence:
    return verify_authority_time_evidence(
        AuthorityTimeEvidence.sealed(
            now_ref="time:now",
            now_epoch_ns=now,
            valid_from_ref="time:start",
            valid_from_epoch_ns=valid_from,
            expires_at_ref=None if expires_at is None else "time:end",
            expires_at_epoch_ns=expires_at,
            source_ref="clock:synthetic",
        )
    )


def approval_intent(application: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "sedb-ral.principal-application-approval-intent/0.1",
        "principal_ref": PRINCIPAL_REF,
        "application_ref": application["application_id"],
        "application_digest": sha256_ref(application),
        "approved_scopes": ["registration.application.approve"],
    }


def raw_principal_item(
    intent: dict[str, object],
    *,
    role: str = "user",
    kind: str = "userMessage",
    status: str = "completed",
    item_ref: str = "user-item:approval",
    turn_id: str = "turn:approval",
) -> RawPrincipalItemSnapshot:
    return RawPrincipalItemSnapshot(
        provider="openai",
        adapter_kind="codex_app_task_tool",
        native_thread_id=PRINCIPAL_THREAD,
        native_turn_id=turn_id,
        source_item_role=role,
        source_item_kind=kind,
        source_item_status=status,
        source_item_parent_thread_id=PRINCIPAL_THREAD,
        source_item_parent_turn_id=turn_id,
        source_item_ref=item_ref,
        content_bytes=canonical_bytes(intent),
    )


def principal_host(raw: RawPrincipalItemSnapshot) -> PrincipalHostObservation:
    return PrincipalHostObservation.sealed(
        provider=raw.provider,
        adapter_kind=raw.adapter_kind,
        native_thread_id=raw.native_thread_id,
        native_turn_id=raw.native_turn_id,
        source_item_role=raw.source_item_role,
        source_item_kind=raw.source_item_kind,
        source_item_status=raw.source_item_status,
        source_item_ref=raw.source_item_ref,
        observed_origin="host:codex-app",
        observed_at_ref="ctcl:instant:principal-host",
    )


def approval_artifact(
    application: dict[str, object],
    raw: RawPrincipalItemSnapshot,
    host: PrincipalHostObservation,
    *,
    principal_ref: str = PRINCIPAL_REF,
    status: str = "active",
) -> PrincipalApplicationApproval:
    return PrincipalApplicationApproval.sealed(
        {
            "schema": "sedb-ral.principal-application-approval/0.1",
            "approval_id": "approval:slot-1",
            "principal_ref": principal_ref,
            "application_ref": application["application_id"],
            "application_digest": sha256_ref(application),
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "approved_scopes": ["registration.application.approve"],
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": status,
            "revoked_by_ref": "revocation:test" if status == "revoked" else None,
            "not_claimed": ["slot_execution", "registrar_authority"],
        }
    )


def verified_approval(tmp_path) -> tuple[VerifiedApplicationApproval, object, object]:
    selected_candidate = candidates(tmp_path)[0]
    application = selected_candidate.prepared.application
    intent = approval_intent(application)
    raw = raw_principal_item(intent)
    host = principal_host(raw)
    artifact = approval_artifact(application, raw, host)
    verified = verify_application_approval(
        artifact,
        application,
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )
    return verified, selected_candidate, application


def execution_intent(
    selected_plan,
    request,
    approval: VerifiedApplicationApproval,
) -> dict[str, object]:
    return {
        "schema": "sedb-ral.registration-slot-execution-intent/0.1",
        "principal_ref": PRINCIPAL_REF,
        "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
        "wave_plan_digest": selected_plan.digest,
        "slot_id": request.slot_id,
        "slot_index": request.slot_index,
        "operation_request_ref": request.request_id,
        "operation_request_digest": request.digest,
        "application_approval_ref": approval.approval.approval_id,
        "application_approval_digest": approval.approval.digest,
        "policy_ref": selected_plan.policy_ref,
        "policy_digest": selected_plan.policy_digest,
        "checkpoint_ref": selected_plan.checkpoint_ref,
        "checkpoint_digest": selected_plan.checkpoint_digest,
        "expected_ledger_head": request.expected_ledger_state[
            "expected_ledger_head"
        ],
        "registry_control_digest": selected_plan.registry_control_digest,
    }


def execution_artifact(
    selected_plan,
    request,
    approval: VerifiedApplicationApproval,
    raw: RawPrincipalItemSnapshot,
    host: PrincipalHostObservation,
) -> SlotExecutionAuthorization:
    return SlotExecutionAuthorization.sealed(
        {
            "schema": "sedb-ral.registration-slot-execution-authorization/0.1",
            "execution_authorization_id": "execution-authorization:slot-1",
            "principal_ref": PRINCIPAL_REF,
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": request.slot_id,
            "slot_index": request.slot_index,
            "operation_request_ref": request.request_id,
            "operation_request_digest": request.digest,
            "application_approval_ref": approval.approval.approval_id,
            "application_approval_digest": approval.approval.digest,
            "policy_ref": selected_plan.policy_ref,
            "policy_digest": selected_plan.policy_digest,
            "checkpoint_ref": selected_plan.checkpoint_ref,
            "checkpoint_digest": selected_plan.checkpoint_digest,
            "expected_ledger_head": request.expected_ledger_state[
                "expected_ledger_head"
            ],
            "registry_control_digest": selected_plan.registry_control_digest,
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "not_claimed": ["batch_execution", "private_access"],
        }
    )


def current_status(
    selected_plan, current_ledger_head: str | None = None
) -> dict[str, object]:
    return {
        "wave_status": "active",
        "policy_ref": selected_plan.policy_ref,
        "policy_digest": selected_plan.policy_digest,
        "checkpoint_ref": selected_plan.checkpoint_ref,
        "checkpoint_digest": selected_plan.checkpoint_digest,
        "registry_generation_digest": selected_plan.registry_generation_digest,
        "registry_control_digest": selected_plan.registry_control_digest,
        "current_ledger_head": current_ledger_head,
    }


def test_exact_user_approval_intent_produces_verified_capability(tmp_path):
    verified, _, application = verified_approval(tmp_path)

    assert isinstance(verified, VerifiedApplicationApproval)
    assert verified.application_digest == sha256_ref(application)
    assert verified.approval.status == "active"


def test_authority_time_rejects_arbitrary_source_digest():
    forged = raw_time_evidence()

    with pytest.raises(RALValidationError, match="authority_time_source_mismatch"):
        forged.verify("time:start", "time:end")


def test_raw_authority_time_cannot_issue_application_approval(tmp_path):
    application = candidates(tmp_path)[0].prepared.application
    raw = raw_principal_item(approval_intent(application))
    host = principal_host(raw)
    artifact = approval_artifact(application, raw, host)

    with pytest.raises(RALValidationError, match="verified_authority_time_required"):
        verify_application_approval(
            artifact,
            application,
            raw,
            host,
            expected_principal_ref=PRINCIPAL_REF,
            time=raw_time_evidence(),
        )


def test_changed_clock_mapping_cannot_reuse_source_digest():
    observed = AuthorityTimeEvidence.sealed(
        now_ref="time:now",
        now_epoch_ns=200,
        valid_from_ref="time:start",
        valid_from_epoch_ns=100,
        expires_at_ref="time:end",
        expires_at_epoch_ns=300,
        source_ref="clock:synthetic",
    )

    with pytest.raises(RALValidationError, match="authority_time_source_mismatch"):
        verify_authority_time_evidence(replace(observed, now_epoch_ns=201))


def test_changed_approval_status_invalidates_issued_capability(tmp_path):
    verified, _, application = verified_approval(tmp_path)
    revoked = approval_artifact(
        application,
        verified.raw_item,
        verified.host,
        status="revoked",
    )

    with pytest.raises(
        RALValidationError, match="verified_application_approval_required"
    ):
        replace(verified, approval=revoked).verify_current(time_evidence())


@pytest.mark.parametrize(
    ("role", "kind"),
    (("assistant", "agentMessage"), ("tool", "toolCall"), ("relay", "userMessage")),
)
def test_non_user_principal_evidence_is_unverified(tmp_path, role, kind):
    application = candidates(tmp_path)[0].prepared.application
    raw = raw_principal_item(approval_intent(application), role=role, kind=kind)
    host = principal_host(raw)
    artifact = approval_artifact(application, raw, host)

    with pytest.raises(RALValidationError, match="principal_authorship_unverified"):
        verify_application_approval(
            artifact,
            application,
            raw,
            host,
            expected_principal_ref=PRINCIPAL_REF,
            time=time_evidence(),
        )


def test_wrong_principal_or_expired_approval_is_not_verified(tmp_path):
    application = candidates(tmp_path)[0].prepared.application
    raw = raw_principal_item(approval_intent(application))
    host = principal_host(raw)

    with pytest.raises(RALValidationError, match="principal_approval_mismatch"):
        verify_application_approval(
            approval_artifact(application, raw, host, principal_ref="principal:other"),
            application,
            raw,
            host,
            expected_principal_ref=PRINCIPAL_REF,
            time=time_evidence(),
        )
    with pytest.raises(RALValidationError, match="authority_time_inactive"):
        verify_application_approval(
            approval_artifact(application, raw, host),
            application,
            raw,
            host,
            expected_principal_ref=PRINCIPAL_REF,
            time=time_evidence(now=400),
        )


def test_application_approval_does_not_authorize_execution(tmp_path):
    approval, _, _ = verified_approval(tmp_path)
    verified_candidates = candidates(tmp_path / "wave")
    selected_plan = plan(tmp_path / "plan")
    selected_policy = policy(verified_candidates)
    prefix = verify_wave_receipt_prefix(selected_plan, ())
    request = build_slot_request(
        selected_plan,
        1,
        prefix,
        {"expected_ledger_head": None, "cli_token": "GENESIS", "ledger_event_count": 0},
    )

    with pytest.raises(
        RALValidationError, match="slot_execution_authorization_missing"
    ):
        verify_slot_execution_authorization(
            None,
            selected_plan,
            request,
            approval,
            selected_policy,
            checkpoint(),
            current_status(selected_plan),
            None,
            None,
            expected_principal_ref=PRINCIPAL_REF,
            time=time_evidence(),
        )


def test_exact_jit_authorization_produces_distinct_execution_capability(tmp_path):
    approval, _, _ = verified_approval(tmp_path / "approval")
    verified_candidates = candidates(tmp_path / "wave")
    selected_policy = policy(verified_candidates)
    selected_plan = plan(tmp_path / "plan")
    prefix = verify_wave_receipt_prefix(selected_plan, ())
    request = build_slot_request(
        selected_plan,
        1,
        prefix,
        {"expected_ledger_head": None, "cli_token": "GENESIS", "ledger_event_count": 0},
    )
    intent = execution_intent(selected_plan, request, approval)
    raw = raw_principal_item(
        intent, item_ref="user-item:execution", turn_id="turn:execution"
    )
    host = principal_host(raw)
    artifact = execution_artifact(selected_plan, request, approval, raw, host)

    verified = verify_slot_execution_authorization(
        artifact,
        selected_plan,
        request,
        approval,
        selected_policy,
        checkpoint(),
        current_status(selected_plan),
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )

    assert isinstance(verified, VerifiedSlotExecutionAuthorization)
    assert verified.authorization.operation_request_digest == request.digest
    assert verified.application_approval_digest == approval.approval.digest


def test_jit_authorization_rejects_stale_current_head(tmp_path):
    approval, _, _ = verified_approval(tmp_path / "approval")
    verified_candidates = candidates(tmp_path / "wave")
    selected_policy = policy(verified_candidates)
    selected_plan = plan(tmp_path / "plan")
    prefix = verify_wave_receipt_prefix(selected_plan, ())
    request = build_slot_request(
        selected_plan,
        1,
        prefix,
        {"expected_ledger_head": None, "cli_token": "GENESIS", "ledger_event_count": 0},
    )
    intent = execution_intent(selected_plan, request, approval)
    raw = raw_principal_item(
        intent, item_ref="user-item:execution", turn_id="turn:execution"
    )
    host = principal_host(raw)
    artifact = execution_artifact(selected_plan, request, approval, raw, host)
    stale = current_status(selected_plan)
    stale["current_ledger_head"] = digest("other-head")

    with pytest.raises(RALValidationError, match="slot_execution_binding_mismatch"):
        verify_slot_execution_authorization(
            artifact,
            selected_plan,
            request,
            approval,
            selected_policy,
            checkpoint(),
            stale,
            raw,
            host,
            expected_principal_ref=PRINCIPAL_REF,
            time=time_evidence(),
        )
