from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

from .application import authority_digest
from .canonical import sha256_ref
from .errors import RALValidationError
from .ledger import LedgerStatus, read_verified_events, verify_ledger
from .projection import RegistryProjection, project_events
from .registrar import (
    RegistrarAdmissionPlan,
    build_admission_plan,
    commit_admission_plan,
)
from .registration_admission import RegistrationDecision, evaluate_prepared_registration
from .registration_wave_authority import VerifiedSlotExecutionAuthorization
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_intake import VerifiedPreparedCandidate
from .registration_wave_models import (
    RegistrationWavePlan,
    SyntheticWaveSlotExecutionResult,
    WaveSlotRequest,
)
from .registration_wave_policy import (
    registration_wave_status,
    require_wave_execution,
)
from .registration_wave_store import RegistrationWaveStore
from .registry_root import RegistryStorage

_PLANNED_TOKEN = object()


def _execution_status_view(
    status: Mapping[str, object],
    plan: RegistrationWavePlan,
    request: WaveSlotRequest,
) -> dict[str, object]:
    return {
        "wave_status": status["wave_status"],
        "policy_ref": plan.policy_ref,
        "policy_digest": plan.policy_digest,
        "checkpoint_ref": plan.checkpoint_ref,
        "checkpoint_digest": plan.checkpoint_digest,
        "registry_generation_digest": plan.registry_generation_digest,
        "registry_control_digest": plan.registry_control_digest,
        "current_ledger_head": request.expected_ledger_state[
            "expected_ledger_head"
        ],
    }


@dataclass(frozen=True)
class PlannedWaveSlot:
    candidate: VerifiedPreparedCandidate
    wave_plan: RegistrationWavePlan
    slot_request: WaveSlotRequest
    execution_authorization: VerifiedSlotExecutionAuthorization
    policy_context: SyntheticWaveExecutionContext
    policy_storage: RegistryStorage
    policy_time: object
    application_authority: dict[str, object]
    verified_attestation_refs: frozenset[str]
    ctcl_receipt: dict[str, object]
    ledger_root: Path
    staging_parent: Path
    decision: RegistrationDecision
    registrar_plan: RegistrarAdmissionPlan
    policy_status_digest: str
    plan_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _PLANNED_TOKEN:
            raise RALValidationError(
                "planned_wave_slot_required",
                "planned slot capability was not issued by the planner",
            )

    def verify(self, context: SyntheticWaveExecutionContext) -> None:
        self.candidate.verify()
        self.execution_authorization.verify()
        status = registration_wave_status(
            self.policy_context, self.policy_storage, self.policy_time
        )
        require_wave_execution(status)
        status_view = _execution_status_view(
            status, self.wave_plan, self.slot_request
        )
        material = {
            "candidate_capability_digest": self.candidate.verification_digest,
            "wave_plan_digest": self.wave_plan.digest,
            "slot_request_digest": self.slot_request.digest,
            "execution_authorization_digest": self.execution_authorization.verification_digest,
            "application_authority_digest": authority_digest(
                self.application_authority
            ),
            "verified_attestation_refs": sorted(self.verified_attestation_refs),
            "ctcl_receipt_digest": sha256_ref(self.ctcl_receipt),
            "registrar_plan_digest": self.registrar_plan.digest,
            "policy_status_digest": sha256_ref(status_view),
        }
        if (
            self.policy_status_digest != sha256_ref(status_view)
            or self.plan_digest != sha256_ref(material)
        ):
            raise RALValidationError(
                "planned_wave_slot_stale", "planned slot bindings changed"
            )


def _source_projection(root: Path, expected_head: str | None) -> RegistryProjection:
    if expected_head is None:
        verification = verify_ledger(root)
        if verification.status not in {LedgerStatus.EMPTY}:
            raise RALValidationError(
                "wave_ledger_state_invalid", "GENESIS ledger is not empty"
            )
        return project_events(())
    return project_events(read_verified_events(root, expected_head))


def plan_wave_slot(
    context: SyntheticWaveExecutionContext,
    *,
    candidate: VerifiedPreparedCandidate,
    wave_plan: Mapping[str, object] | RegistrationWavePlan,
    slot_request: Mapping[str, object] | WaveSlotRequest,
    execution_authorization: VerifiedSlotExecutionAuthorization,
    policy_context: SyntheticWaveExecutionContext,
    policy_storage: RegistryStorage,
    policy_time: object,
    application_authority: Mapping[str, object],
    verified_attestation_refs: AbstractSet[str],
    ctcl_receipt: Mapping[str, object],
    ledger_root: Path,
    staging_parent: Path,
) -> PlannedWaveSlot:
    if not isinstance(candidate, VerifiedPreparedCandidate):
        raise RALValidationError(
            "verified_candidate_required", "slot planner requires verified candidate"
        )
    if not isinstance(
        execution_authorization, VerifiedSlotExecutionAuthorization
    ):
        raise RALValidationError(
            "verified_slot_execution_required",
            "slot planner requires verified execution authorization",
        )
    candidate.verify()
    execution_authorization.verify()
    plan = (
        wave_plan
        if isinstance(wave_plan, RegistrationWavePlan)
        else RegistrationWavePlan.from_dict(wave_plan)
    )
    request = (
        slot_request
        if isinstance(slot_request, WaveSlotRequest)
        else WaveSlotRequest.from_dict(slot_request)
    )
    context.verify_before_io("slot_plan", Path(ledger_root))
    context.verify_before_io("slot_stage", Path(staging_parent))
    status = registration_wave_status(policy_context, policy_storage, policy_time)
    require_wave_execution(status)
    slot = plan.ordered_slots[request.slot_index - 1]
    if (
        request.wave_plan_digest != plan.digest
        or request.candidate_ref != candidate.candidate.candidate_id
        or request.candidate_digest != candidate.digest
        or request.application_ref != candidate.application_ref
        or request.application_digest != candidate.application_digest
        or slot["candidate_digest"] != candidate.digest
        or slot["application_digest"] != candidate.application_digest
        or execution_authorization.plan_digest != plan.digest
        or execution_authorization.request_digest != request.digest
        or execution_authorization.application_approval_digest
        != execution_authorization.approval.approval.digest
        or execution_authorization.approval.application_digest
        != candidate.application_digest
    ):
        raise RALValidationError(
            "wave_slot_candidate_mismatch",
            "candidate, request, plan, approval, or authorization differs",
        )
    status_view = _execution_status_view(status, plan, request)
    if sha256_ref(status_view) != execution_authorization.current_status_digest:
        raise RALValidationError(
            "wave_slot_policy_status_mismatch", "execution status changed"
        )
    canonical_authority = dict(application_authority)
    projection = _source_projection(
        Path(ledger_root), request.expected_ledger_state["expected_ledger_head"]
    )
    decision = evaluate_prepared_registration(
        candidate.prepared,
        [canonical_authority],
        verified_attestation_refs=verified_attestation_refs,
        projection=projection,
    )
    if decision.decision != "accept":
        raise RALValidationError(
            "wave_slot_decision_not_accepted",
            f"registration decision is {decision.decision}",
        )
    Path(staging_parent).mkdir(parents=True, exist_ok=True)
    registrar_plan = build_admission_plan(
        Path(ledger_root),
        candidate.prepared,
        decision,
        canonical_authority,
        dict(ctcl_receipt),
        expected_head=request.expected_ledger_state["expected_ledger_head"],
        verified_attestation_refs=verified_attestation_refs,
        staging_parent=Path(staging_parent),
    )
    context.journal.record("staging_writes", f"registrar-plan:{registrar_plan.digest}")
    frozen_attestations = frozenset(verified_attestation_refs)
    status_digest = sha256_ref(status_view)
    material = {
        "candidate_capability_digest": candidate.verification_digest,
        "wave_plan_digest": plan.digest,
        "slot_request_digest": request.digest,
        "execution_authorization_digest": execution_authorization.verification_digest,
        "application_authority_digest": authority_digest(canonical_authority),
        "verified_attestation_refs": sorted(frozen_attestations),
        "ctcl_receipt_digest": sha256_ref(dict(ctcl_receipt)),
        "registrar_plan_digest": registrar_plan.digest,
        "policy_status_digest": status_digest,
    }
    return PlannedWaveSlot(
        candidate=candidate,
        wave_plan=plan,
        slot_request=request,
        execution_authorization=execution_authorization,
        policy_context=policy_context,
        policy_storage=policy_storage,
        policy_time=policy_time,
        application_authority=canonical_authority,
        verified_attestation_refs=frozen_attestations,
        ctcl_receipt=dict(ctcl_receipt),
        ledger_root=Path(ledger_root),
        staging_parent=Path(staging_parent),
        decision=decision,
        registrar_plan=registrar_plan,
        policy_status_digest=status_digest,
        plan_digest=sha256_ref(material),
        _token=_PLANNED_TOKEN,
    )


def _projection_digests(
    projection: RegistryProjection,
    candidate: VerifiedPreparedCandidate,
) -> dict[str, str]:
    application_id = str(candidate.prepared.application["application_id"])
    resident_id = str(candidate.prepared.application["claimed_resident_id"])
    resident = projection.residents[resident_id]
    instance_id = str(candidate.prepared.application["instance_claims"][0]["instance_id"])
    address_id = str(candidate.prepared.application["addresses"][0]["address_id"])
    instance = next(value for value in resident["instances"] if value["instance_id"] == instance_id)
    address = next(value for value in resident["addresses"] if value["address_id"] == address_id)
    return {
        "application": sha256_ref(projection.applications[application_id]),
        "resident": sha256_ref(resident),
        "instance": sha256_ref(instance),
        "address": sha256_ref(address),
        "binding": sha256_ref(projection.directory[resident_id]),
    }


def simulate_wave_slot(
    context: SyntheticWaveExecutionContext,
    planned: PlannedWaveSlot,
    store: RegistrationWaveStore,
) -> SyntheticWaveSlotExecutionResult:
    if not isinstance(planned, PlannedWaveSlot):
        raise RALValidationError(
            "planned_wave_slot_required", "simulate requires planned slot capability"
        )
    planned.verify(context)
    context.verify_before_io("slot_commit", planned.ledger_root)
    receipt = commit_admission_plan(
        planned.ledger_root,
        planned.registrar_plan,
        planned.candidate.prepared,
        planned.decision,
        planned.application_authority,
        planned.ctcl_receipt,
        verified_attestation_refs=planned.verified_attestation_refs,
    )
    events = read_verified_events(planned.ledger_root, receipt.final_head)
    event_by_id = {str(value["event_id"]): value for value in events}
    appended = [event_by_id[event_id] for event_id in receipt.event_ids]
    projection = project_events(events)
    material = {
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
        "pre_head": receipt.source_head,
        "post_head": receipt.final_head,
        "appended_events": [
            {"event_ref": str(value["event_id"]), "event_digest": sha256_ref(value)}
            for value in appended
        ],
        "projection_digests": _projection_digests(
            projection, planned.candidate
        ),
        "execution_scope": "synthetic",
        "production_wave_run": "NOT_RUN",
        "live_limen_b6a": "NOT_RUN",
        "not_claimed": ["production_admission", "live_limen_resolution"],
    }
    result = SyntheticWaveSlotExecutionResult.sealed(material)
    stored = store.put_slot_result(str(planned.slot_request.slot_id), result)
    if receipt.committed:
        for event_id in receipt.event_ids:
            context.journal.record("synthetic_ledger_writes", f"ledger-event:{event_id}")
    if stored.kind == "created":
        context.journal.record("synthetic_receipt_writes", str(result.result_id))
    return result
