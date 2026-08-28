from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .canonical import sha256_ref
from .errors import RALValidationError
from .ledger import LedgerStatus, read_verified_events, verify_ledger
from .projection import project_events
from .registrar import find_committed_registration, inspect_registration_prefix
from .registration_wave_authority import (
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedAuthorityTimeEvidence,
    _verify_user_item,
)
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_engine import PlannedWaveSlot, _projection_digests
from .registration_wave_models import (
    SyntheticWaveSlotExecutionResult,
    SyntheticWaveSlotRecoveryResult,
    WaveSlotRecoveryAuthorization,
)
from .registration_wave_store import (
    RegistrationWaveStore,
    issue_verified_synthetic_recovery_result,
    issue_verified_synthetic_slot_result,
)

_RECOVERY_TOKEN = object()


@dataclass(frozen=True)
class WaveSlotPrefixInspection:
    status: str
    wave_plan_digest: str
    slot_request_digest: str
    application_digest: str
    current_head: str | None
    event_count: int
    prefix_digest: str
    stored_result_digest: str | None


@dataclass(frozen=True)
class VerifiedWaveSlotRecoveryAuthorization:
    authorization: WaveSlotRecoveryAuthorization
    inspection_digest: str
    planned_slot_digest: str
    raw_item: RawPrincipalItemSnapshot = field(repr=False)
    host: PrincipalHostObservation
    issuance_time: VerifiedAuthorityTimeEvidence
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _RECOVERY_TOKEN:
            raise RALValidationError(
                "verified_wave_recovery_authority_required",
                "recovery authority was not verifier-issued",
            )

    def verify(self) -> None:
        self.host.verify()
        self.issuance_time.verify()
        material = {
            "authorization_digest": self.authorization.digest,
            "inspection_digest": self.inspection_digest,
            "planned_slot_digest": self.planned_slot_digest,
            "raw_item_digest": self.raw_item.evidence_digest,
            "host_observation_digest": self.host.digest,
            "issuance_time_digest": self.issuance_time.verification_digest,
        }
        if sha256_ref(material) != self.verification_digest:
            raise RALValidationError(
                "verified_wave_recovery_authority_required",
                "recovery authority capability digest differs",
            )

    def verify_current(self, time: VerifiedAuthorityTimeEvidence) -> None:
        self.verify()
        if not isinstance(time, VerifiedAuthorityTimeEvidence):
            raise RALValidationError(
                "verified_authority_time_required",
                "fresh recovery authority time is required",
            )
        time.verify_against(self.issuance_time)


def _inspection_digest(value: WaveSlotPrefixInspection) -> str:
    return sha256_ref(
        {
            "status": value.status,
            "wave_plan_digest": value.wave_plan_digest,
            "slot_request_digest": value.slot_request_digest,
            "application_digest": value.application_digest,
            "current_head": value.current_head,
            "event_count": value.event_count,
            "prefix_digest": value.prefix_digest,
            "stored_result_digest": value.stored_result_digest,
        }
    )


def _prefix_evidence_digest(value: WaveSlotPrefixInspection) -> str:
    return sha256_ref(
        {
            "wave_plan_digest": value.wave_plan_digest,
            "slot_request_digest": value.slot_request_digest,
            "application_digest": value.application_digest,
            "current_head": value.current_head,
            "event_count": value.event_count,
            "prefix_digest": value.prefix_digest,
        }
    )


def _planned_digest(planned: PlannedWaveSlot) -> str:
    return sha256_ref(
        {
            "planned_digest": planned.plan_digest,
            "wave_plan_digest": planned.wave_plan.digest,
            "slot_request_digest": planned.slot_request.digest,
            "execution_authorization_digest": planned.execution_authorization.authorization.digest,
            "application_approval_digest": planned.execution_authorization.approval.approval.digest,
            "checkpoint_digest": planned.wave_plan.checkpoint_digest,
        }
    )


def inspect_wave_slot_prefix(
    context: SyntheticWaveExecutionContext,
    planned: PlannedWaveSlot,
    store: RegistrationWaveStore,
) -> WaveSlotPrefixInspection:
    if not isinstance(planned, PlannedWaveSlot):
        raise RALValidationError(
            "planned_wave_slot_required", "prefix inspection requires planned slot"
        )
    planned.verify_static()
    context.verify_before_io("recovery_inspect", planned.ledger_root)
    verification = verify_ledger(planned.ledger_root)
    if verification.status is LedgerStatus.INVALID:
        raise RALValidationError(
            "wave_recovery_ledger_invalid", "synthetic ledger is invalid"
        )
    if verification.status is LedgerStatus.EMPTY:
        events: tuple[dict[str, object], ...] = ()
        current_head = None
    else:
        current_head = verification.final_chain_digest
        if current_head is None:
            raise RALValidationError(
                "wave_recovery_ledger_invalid", "nonempty ledger lacks head"
            )
        events = read_verified_events(planned.ledger_root, current_head)
    prefix_state = inspect_registration_prefix(
        events, planned.candidate.application_digest
    )
    prefix_digest = sha256_ref(list(events))
    stored_slot = store.get_slot_result(str(planned.slot_request.slot_id))
    stored_recovery = store.get_recovery_result(str(planned.slot_request.slot_id))
    if stored_slot is not None and stored_recovery is not None:
        raise RALValidationError(
            "wave_recovery_result_mismatch",
            "slot has both execution and recovery results",
        )
    if prefix_state == "complete":
        if stored_slot is None and stored_recovery is None:
            status = "recovery_required"
        elif (
            stored_slot is not None
            and stored_slot.wave_plan_digest == planned.wave_plan.digest
            and stored_slot.slot_request_digest == planned.slot_request.digest
            and stored_slot.post_head == current_head
        ) or (
            stored_recovery is not None
            and stored_recovery.verified_prefix_digest == prefix_digest
            and stored_recovery.pre_head
            == planned.slot_request.expected_ledger_state["expected_ledger_head"]
            and stored_recovery.post_head == current_head
        ):
            status = "durable_receipt"
        else:
            raise RALValidationError(
                "wave_recovery_result_mismatch",
                "stored synthetic result differs from complete ledger",
            )
    elif prefix_state == "partial":
        if stored_slot is not None or stored_recovery is not None:
            raise RALValidationError(
                "wave_recovery_result_mismatch",
                "partial prefix cannot have a durable synthetic result",
            )
        status = "registrar_partial_transaction"
    elif prefix_state == "absent":
        if stored_slot is not None or stored_recovery is not None:
            raise RALValidationError(
                "wave_recovery_result_mismatch",
                "absent prefix cannot have a durable synthetic result",
            )
        status = "absent"
    else:
        raise RALValidationError(
            "wave_recovery_prefix_conflicting",
            "registration prefix is conflicting",
        )
    return WaveSlotPrefixInspection(
        status=status,
        wave_plan_digest=planned.wave_plan.digest,
        slot_request_digest=planned.slot_request.digest,
        application_digest=planned.candidate.application_digest,
        current_head=current_head,
        event_count=len(events),
        prefix_digest=prefix_digest,
        stored_result_digest=(
            stored_slot.digest
            if stored_slot is not None
            else None if stored_recovery is None else stored_recovery.digest
        ),
    )


def verify_wave_slot_recovery_authorization(
    authorization: Mapping[str, object] | WaveSlotRecoveryAuthorization,
    inspection: WaveSlotPrefixInspection,
    planned: PlannedWaveSlot,
    principal_item: RawPrincipalItemSnapshot,
    host_observation: PrincipalHostObservation,
    *,
    expected_principal_ref: str,
    time: VerifiedAuthorityTimeEvidence,
) -> VerifiedWaveSlotRecoveryAuthorization:
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "recovery authority requires verified time evidence",
        )
    parsed = (
        authorization
        if isinstance(authorization, WaveSlotRecoveryAuthorization)
        else WaveSlotRecoveryAuthorization.from_dict(authorization)
    )
    if inspection.status != "recovery_required":
        raise RALValidationError(
            "wave_recovery_state_invalid",
            "recovery authority requires a complete prefix without outer result",
        )
    if (
        inspection.wave_plan_digest != planned.wave_plan.digest
        or inspection.slot_request_digest != planned.slot_request.digest
        or inspection.application_digest != planned.candidate.application_digest
        or inspection.stored_result_digest is not None
    ):
        raise RALValidationError(
            "wave_recovery_inspection_mismatch",
            "recovery inspection binds another planned slot",
        )
    expected_intent = {
        "schema": "sedb-ral.registration-wave-slot-recovery-intent/0.1",
        "principal_ref": expected_principal_ref,
        "wave_plan_digest": planned.wave_plan.digest,
        "slot_id": planned.slot_request.slot_id,
        "slot_request_digest": planned.slot_request.digest,
        "original_execution_authorization_digest": planned.execution_authorization.authorization.digest,
        "application_approval_digest": planned.execution_authorization.approval.approval.digest,
        "verified_prefix_digest": inspection.prefix_digest,
        "pre_head": planned.slot_request.expected_ledger_state[
            "expected_ledger_head"
        ],
        "post_head": inspection.current_head,
        "checkpoint_digest": planned.wave_plan.checkpoint_digest,
        "current_readback_digest": inspection.prefix_digest,
    }
    _verify_user_item(principal_item, host_observation, expected_intent)
    if (
        parsed.principal_ref != expected_principal_ref
        or parsed.wave_plan_ref
        != f"registration-wave-plan:{planned.wave_plan.wave_id}"
        or parsed.wave_plan_digest != planned.wave_plan.digest
        or parsed.slot_id != planned.slot_request.slot_id
        or parsed.slot_request_ref != planned.slot_request.request_id
        or parsed.slot_request_digest != planned.slot_request.digest
        or parsed.original_execution_authorization_ref
        != planned.execution_authorization.authorization.execution_authorization_id
        or parsed.original_execution_authorization_digest
        != planned.execution_authorization.authorization.digest
        or parsed.application_approval_ref
        != planned.execution_authorization.approval.approval.approval_id
        or parsed.application_approval_digest
        != planned.execution_authorization.approval.approval.digest
        or parsed.verified_prefix_digest != inspection.prefix_digest
        or parsed.pre_head
        != planned.slot_request.expected_ledger_state["expected_ledger_head"]
        or parsed.post_head != inspection.current_head
        or parsed.checkpoint_ref != planned.wave_plan.checkpoint_ref
        or parsed.checkpoint_digest != planned.wave_plan.checkpoint_digest
        or parsed.current_readback_digest != inspection.prefix_digest
        or parsed.source_user_item_ref != principal_item.source_item_ref
        or parsed.source_user_item_digest != principal_item.evidence_digest
        or parsed.host_observation_ref != host_observation.observation_ref
        or parsed.host_observation_digest != host_observation.digest
        or parsed.status != "active"
    ):
        raise RALValidationError(
            "wave_recovery_authorization_mismatch",
            "recovery authorization bindings differ",
        )
    time.verify_current(parsed.valid_from_ref, parsed.expires_at_ref)
    inspection_digest = _inspection_digest(inspection)
    planned_digest = _planned_digest(planned)
    material = {
        "authorization_digest": parsed.digest,
        "inspection_digest": inspection_digest,
        "planned_slot_digest": planned_digest,
        "raw_item_digest": principal_item.evidence_digest,
        "host_observation_digest": host_observation.digest,
        "issuance_time_digest": time.verification_digest,
    }
    return VerifiedWaveSlotRecoveryAuthorization(
        authorization=parsed,
        inspection_digest=inspection_digest,
        planned_slot_digest=planned_digest,
        raw_item=principal_item,
        host=host_observation,
        issuance_time=time,
        verification_digest=sha256_ref(material),
        _token=_RECOVERY_TOKEN,
    )


def _reconstruct_execution_result(
    planned: PlannedWaveSlot,
    events: tuple[dict[str, object], ...],
    event_ids: tuple[str, ...],
    final_head: str,
) -> SyntheticWaveSlotExecutionResult:
    event_by_id = {str(value["event_id"]): value for value in events}
    projection = project_events(events)
    return SyntheticWaveSlotExecutionResult.sealed(
        {
            "schema": "sedb-ral.synthetic-wave-slot-execution-result/0.1",
            "result_id": f"synthetic-slot-result:{planned.slot_request.slot_index}",
            "wave_plan_ref": planned.slot_request.wave_plan_ref,
            "wave_plan_digest": planned.wave_plan.digest,
            "slot_id": planned.slot_request.slot_id,
            "slot_index": planned.slot_request.slot_index,
            "slot_request_ref": planned.slot_request.request_id,
            "slot_request_digest": planned.slot_request.digest,
            "execution_authorization_ref": planned.execution_authorization.authorization.execution_authorization_id,
            "execution_authorization_digest": planned.execution_authorization.authorization.digest,
            "application_approval_ref": planned.execution_authorization.approval.approval.approval_id,
            "application_approval_digest": planned.execution_authorization.approval.approval.digest,
            "pre_head": planned.slot_request.expected_ledger_state[
                "expected_ledger_head"
            ],
            "post_head": final_head,
            "appended_events": [
                {
                    "event_ref": event_id,
                    "event_digest": sha256_ref(event_by_id[event_id]),
                }
                for event_id in event_ids
            ],
            "projection_digests": _projection_digests(
                projection, planned.candidate
            ),
            "execution_scope": "synthetic",
            "production_wave_run": "NOT_RUN",
            "live_limen_b6a": "NOT_RUN",
            "not_claimed": ["production_admission", "live_limen_resolution"],
        }
    )


def recover_synthetic_wave_slot_result(
    context: SyntheticWaveExecutionContext,
    authorization: VerifiedWaveSlotRecoveryAuthorization | None,
    inspection: WaveSlotPrefixInspection,
    planned: PlannedWaveSlot,
    store: RegistrationWaveStore,
    *,
    time: VerifiedAuthorityTimeEvidence,
) -> SyntheticWaveSlotRecoveryResult:
    if authorization is None:
        raise RALValidationError(
            "wave_recovery_authorization_missing",
            "recovery requires separate verified authority",
        )
    if not isinstance(authorization, VerifiedWaveSlotRecoveryAuthorization):
        raise RALValidationError(
            "verified_wave_recovery_authority_required",
            "plain recovery authority cannot recover a result",
        )
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "recovery requires fresh verified time",
        )
    authorization.verify_current(time)
    if (
        authorization.inspection_digest != _inspection_digest(inspection)
        or authorization.planned_slot_digest != _planned_digest(planned)
    ):
        raise RALValidationError(
            "verified_wave_recovery_authority_required",
            "recovery capability does not bind the supplied inspection and slot",
        )
    current = inspect_wave_slot_prefix(context, planned, store)
    existing_recovery = store.get_recovery_result(str(planned.slot_request.slot_id))
    if current.status == "durable_receipt" and existing_recovery is not None:
        if (
            _prefix_evidence_digest(current)
            != _prefix_evidence_digest(inspection)
            or existing_recovery.recovery_authorization_digest
            != authorization.authorization.digest
            or existing_recovery.verified_prefix_digest != current.prefix_digest
        ):
            raise RALValidationError(
                "wave_recovery_result_mismatch", "stored recovery result differs"
            )
        return existing_recovery
    if _inspection_digest(current) != authorization.inspection_digest:
        raise RALValidationError(
            "wave_recovery_prefix_changed", "registration prefix changed"
        )
    if current.status != "recovery_required":
        raise RALValidationError(
            "wave_recovery_state_invalid",
            f"cannot recover from {current.status}",
        )
    events = read_verified_events(planned.ledger_root, current.current_head)
    core = find_committed_registration(
        events, planned.candidate.application_digest
    )
    if core is None or core.final_head != current.current_head:
        raise RALValidationError(
            "wave_recovery_core_receipt_missing",
            "complete registration cannot be reconstructed",
        )
    execution_result = _reconstruct_execution_result(
        planned, events, core.event_ids, core.final_head
    )
    verified_execution_result = issue_verified_synthetic_slot_result(
        execution_result,
        planned.execution_authorization,
        planned.application_authority,
        planned_slot_digest=planned.plan_digest,
        prefix_plan_digest=planned.result_prefix.plan_digest,
        prefix_verification_digest=planned.result_prefix.verification_digest,
        prefix_result_digests=tuple(
            value.digest for value in planned.result_prefix.results
        ),
        prefix_final_head=planned.result_prefix.final_head,
        prefix_event_count=planned.result_prefix.ledger_event_count,
        time=planned.policy_time,
    )
    recovery = SyntheticWaveSlotRecoveryResult.sealed(
        {
            "schema": "sedb-ral.synthetic-wave-slot-recovery-result/0.1",
            "result_id": f"synthetic-recovery-result:{planned.slot_request.slot_index}",
            "recovery_authorization_ref": authorization.authorization.recovery_authorization_id,
            "recovery_authorization_digest": authorization.authorization.digest,
            "verified_prefix_digest": current.prefix_digest,
            "pre_head": planned.slot_request.expected_ledger_state[
                "expected_ledger_head"
            ],
            "post_head": core.final_head,
            "reconstructed_result_ref": execution_result.result_id,
            "reconstructed_result_digest": execution_result.digest,
            "execution_scope": "synthetic",
            "production_wave_run": "NOT_RUN",
            "live_limen_b6a": "NOT_RUN",
            "status": "recovered_synthetic",
            "not_claimed": ["production_recovery", "accepted_admission"],
        }
    )
    verified_recovery = issue_verified_synthetic_recovery_result(
        recovery,
        recovery_authorization=authorization.authorization,
        recovery_raw_item=authorization.raw_item,
        recovery_host=authorization.host,
        recovery_time=authorization.issuance_time,
        recovery_inspection_digest=authorization.inspection_digest,
        recovery_planned_slot_digest=authorization.planned_slot_digest,
        recovery_capability_digest=authorization.verification_digest,
        reconstructed_result=verified_execution_result,
    )
    stored = store.put_recovery_result(
        str(planned.slot_request.slot_id), verified_recovery
    )
    if stored.kind == "created":
        context.journal.record("synthetic_receipt_writes", str(recovery.result_id))
    return recovery


def plan_wave_continuation(
    context: SyntheticWaveExecutionContext,
    inspection: WaveSlotPrefixInspection,
    planned: PlannedWaveSlot,
) -> dict[str, object]:
    context.verify_before_io("continuation_plan", planned.ledger_root)
    return {
        "schema": "sedb-ral.registration-wave-continuation-plan/0.1",
        "wave_plan_digest": planned.wave_plan.digest,
        "slot_request_digest": planned.slot_request.digest,
        "prefix_digest": inspection.prefix_digest,
        "prefix_status": inspection.status,
        "continuation_status": "separate_authority_required",
        "automatic_resume": False,
        "required_evidence": [
            "new_policy",
            "fresh_checkpoint",
            "current_head_readback",
            "fresh_execution_authorization",
        ],
    }
