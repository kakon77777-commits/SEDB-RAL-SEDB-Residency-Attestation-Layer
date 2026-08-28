from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

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
from .registration_wave_authority import (
    VerifiedApplicationAuthority,
    VerifiedAuthorityTimeEvidence,
    VerifiedSlotExecutionAuthorization,
)
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
from .registration_wave_store import (
    RegistrationWaveStore,
    issue_verified_synthetic_slot_result,
)
from .registry_root import RegistryStorage

_PLANNED_TOKEN = object()
_SYNTHETIC_PREFIX_TOKEN = object()


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
class VerifiedSyntheticWaveResultPrefix:
    plan_digest: str
    results: tuple[SyntheticWaveSlotExecutionResult, ...]
    final_head: str | None
    ledger_event_count: int
    verification_digest: str
    store: RegistrationWaveStore = field(repr=False, compare=False)
    ledger_root: Path = field(repr=False, compare=False)
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _SYNTHETIC_PREFIX_TOKEN:
            raise RALValidationError(
                "verified_synthetic_prefix_required",
                "synthetic result prefix was not verifier-issued",
            )

    def verify(
        self,
        context: SyntheticWaveExecutionContext,
        plan: RegistrationWavePlan,
    ) -> None:
        material, results, final_head, event_count = _synthetic_prefix_material(
            context, plan, self.store, self.ledger_root
        )
        if (
            self.plan_digest != plan.digest
            or tuple(value.digest for value in self.results)
            != tuple(value.digest for value in results)
            or self.final_head != final_head
            or self.ledger_event_count != event_count
            or self.verification_digest != sha256_ref(material)
        ):
            raise RALValidationError(
                "verified_synthetic_prefix_required",
                "synthetic result prefix is stale or mismatched",
            )


def _synthetic_prefix_material(
    context: SyntheticWaveExecutionContext,
    plan: RegistrationWavePlan,
    store: RegistrationWaveStore,
    ledger_root: Path,
) -> tuple[
    dict[str, object],
    tuple[SyntheticWaveSlotExecutionResult, ...],
    str | None,
    int,
]:
    if not isinstance(store, RegistrationWaveStore):
        raise RALValidationError(
            "verified_synthetic_prefix_required", "result store is not verified"
        )
    if store.expected_wave_digest != plan.digest:
        raise RALValidationError(
            "verified_synthetic_prefix_required",
            "result store is pinned to another Wave plan",
        )
    canonical_root = Path(ledger_root)
    context.verify_before_io("synthetic_prefix_verify", canonical_root)
    verification = verify_ledger(canonical_root)
    if verification.status is LedgerStatus.INVALID:
        raise RALValidationError(
            "wave_receipt_prefix_invalid", "synthetic ledger is invalid"
        )
    final_head = verification.final_chain_digest
    events = (
        ()
        if verification.status is LedgerStatus.EMPTY
        else read_verified_events(canonical_root, str(final_head))
    )
    observed_capabilities = tuple(
        store.get_verified_slot_result(f"slot:{index}") for index in range(1, 4)
    )
    seen_missing = False
    results: list[SyntheticWaveSlotExecutionResult] = []
    capabilities = []
    for capability in observed_capabilities:
        if capability is None:
            seen_missing = True
        elif seen_missing:
            raise RALValidationError(
                "wave_predecessor_missing", "synthetic result prefix has a gap"
            )
        else:
            capability.verify()
            capabilities.append(capability)
            results.append(capability.result)
    cursor = 0
    previous: SyntheticWaveSlotExecutionResult | None = None
    evidence: list[dict[str, object]] = []
    for index, (result, capability) in enumerate(
        zip(results, capabilities, strict=True), start=1
    ):
        request = store.get_slot_request(f"slot:{index}")
        if request is None:
            raise RALValidationError(
                "wave_predecessor_missing", "stored synthetic result lacks request"
            )
        slot = plan.ordered_slots[index - 1]
        appended = tuple(result.appended_events)
        suffix = events[cursor : cursor + len(appended)]
        observed_pairs = tuple(
            {
                "event_ref": str(value["event_id"]),
                "event_digest": sha256_ref(value),
            }
            for value in suffix
        )
        previous_head = None if previous is None else previous.post_head
        predecessor_ref = None if previous is None else previous.result_id
        predecessor_digest = None if previous is None else previous.digest
        prior_material = {
            "plan_digest": plan.digest,
            "evidence": list(evidence),
            "final_head": previous_head,
            "ledger_event_count": cursor,
        }
        if (
            capability.prefix_plan_digest != plan.digest
            or capability.prefix_verification_digest != sha256_ref(prior_material)
            or capability.prefix_result_digests
            != tuple(value.digest for value in results[: index - 1])
            or capability.prefix_final_head != previous_head
            or capability.prefix_event_count != cursor
            or tuple(capability.ledger_events)
            != tuple(events[: cursor + len(suffix)])
            or result.wave_plan_digest != plan.digest
            or result.slot_id != slot["slot_id"]
            or result.slot_index != index
            or result.slot_request_ref != request.request_id
            or result.slot_request_digest != request.digest
            or result.pre_head != previous_head
            or request.wave_plan_digest != plan.digest
            or request.slot_id != slot["slot_id"]
            or request.slot_index != index
            or request.candidate_ref != slot["candidate_ref"]
            or request.candidate_digest != slot["candidate_digest"]
            or request.application_ref != slot["application_ref"]
            or request.application_digest != slot["application_digest"]
            or request.predecessor_receipt_ref != predecessor_ref
            or request.predecessor_receipt_digest != predecessor_digest
            or request.expected_ledger_state["expected_ledger_head"]
            != previous_head
            or request.expected_ledger_state["ledger_event_count"] != cursor
            or tuple(appended) != observed_pairs
            or not suffix
            or result.post_head != suffix[-1]["integrity"]["chain_digest"]
        ):
            raise RALValidationError(
                "wave_receipt_prefix_invalid",
                "synthetic result does not extend the exact durable prefix",
            )
        cursor += len(suffix)
        evidence.append(
            {
                "slot_index": index,
                "request_digest": request.digest,
                "result_digest": result.digest,
                "post_head": result.post_head,
                "event_count": cursor,
            }
        )
        previous = result
    expected_head = None if previous is None else previous.post_head
    if cursor != len(events) or final_head != expected_head:
        raise RALValidationError(
            "wave_receipt_prefix_invalid",
            "ledger and durable synthetic result prefix differ",
        )
    material = {
        "plan_digest": plan.digest,
        "evidence": evidence,
        "final_head": final_head,
        "ledger_event_count": len(events),
    }
    return material, tuple(results), final_head, len(events)


def verify_synthetic_wave_result_prefix(
    context: SyntheticWaveExecutionContext,
    plan: Mapping[str, object] | RegistrationWavePlan,
    store: RegistrationWaveStore,
    ledger_root: Path,
) -> VerifiedSyntheticWaveResultPrefix:
    parsed_plan = (
        plan
        if isinstance(plan, RegistrationWavePlan)
        else RegistrationWavePlan.from_dict(plan)
    )
    material, results, final_head, event_count = _synthetic_prefix_material(
        context, parsed_plan, store, Path(ledger_root)
    )
    return VerifiedSyntheticWaveResultPrefix(
        plan_digest=parsed_plan.digest,
        results=results,
        final_head=final_head,
        ledger_event_count=event_count,
        verification_digest=sha256_ref(material),
        store=store,
        ledger_root=Path(ledger_root),
        _token=_SYNTHETIC_PREFIX_TOKEN,
    )


@dataclass(frozen=True)
class PlannedWaveSlot:
    candidate: VerifiedPreparedCandidate
    wave_plan: RegistrationWavePlan
    slot_request: WaveSlotRequest
    execution_authorization: VerifiedSlotExecutionAuthorization
    result_prefix: VerifiedSyntheticWaveResultPrefix
    policy_context: SyntheticWaveExecutionContext
    policy_storage: RegistryStorage
    policy_time: VerifiedAuthorityTimeEvidence
    application_authority: VerifiedApplicationAuthority
    ctcl_receipt: dict[str, object]
    ledger_root: Path
    staging_parent: Path
    decision: RegistrationDecision
    registrar_plan: RegistrarAdmissionPlan
    policy_status_digest: str
    planning_time_digest: str
    plan_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _PLANNED_TOKEN:
            raise RALValidationError(
                "planned_wave_slot_required",
                "planned slot capability was not issued by the planner",
            )

    def _material(self) -> dict[str, object]:
        return {
            "candidate_capability_digest": self.candidate.verification_digest,
            "wave_plan_digest": self.wave_plan.digest,
            "slot_request_digest": self.slot_request.digest,
            "execution_authorization_digest": self.execution_authorization.verification_digest,
            "result_prefix_digest": self.result_prefix.verification_digest,
            "application_authority_capability_digest": self.application_authority.verification_digest,
            "ctcl_receipt_digest": sha256_ref(self.ctcl_receipt),
            "registrar_plan_digest": self.registrar_plan.digest,
            "policy_status_digest": self.policy_status_digest,
            "planning_time_digest": self.planning_time_digest,
        }

    def verify_static(self) -> None:
        self.candidate.verify()
        self.policy_time.verify()
        self.execution_authorization.verify()
        self.application_authority.verify_current(
            self.execution_authorization, self.application_authority.issuance_time
        )
        if (
            self.planning_time_digest != self.policy_time.verification_digest
            or self.plan_digest != sha256_ref(self._material())
        ):
            raise RALValidationError(
                "planned_wave_slot_stale", "planned slot bindings changed"
            )

    def verify(
        self,
        context: SyntheticWaveExecutionContext,
        time: VerifiedAuthorityTimeEvidence,
    ) -> None:
        self.verify_static()
        if not isinstance(time, VerifiedAuthorityTimeEvidence):
            raise RALValidationError(
                "verified_authority_time_required",
                "slot execution requires fresh verified time",
            )
        self.execution_authorization.verify_current(time)
        self.application_authority.verify_current(
            self.execution_authorization, time
        )
        self.result_prefix.verify(context, self.wave_plan)
        status = registration_wave_status(
            self.policy_context, self.policy_storage, time
        )
        require_wave_execution(status)
        status_view = _execution_status_view(
            status, self.wave_plan, self.slot_request
        )
        if (
            self.policy_status_digest != sha256_ref(status_view)
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
    result_prefix: VerifiedSyntheticWaveResultPrefix,
    policy_context: SyntheticWaveExecutionContext,
    policy_storage: RegistryStorage,
    policy_time: VerifiedAuthorityTimeEvidence,
    application_authority: VerifiedApplicationAuthority,
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
    if not isinstance(policy_time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "slot planning requires fresh verified time",
        )
    if not isinstance(result_prefix, VerifiedSyntheticWaveResultPrefix):
        raise RALValidationError(
            "verified_synthetic_prefix_required",
            "slot planning requires a verified durable synthetic prefix",
        )
    if not isinstance(application_authority, VerifiedApplicationAuthority):
        raise RALValidationError(
            "verified_application_authority_required",
            "slot planning rejects raw authority and attestation values",
        )
    candidate.verify()
    execution_authorization.verify_current(policy_time)
    application_authority.verify_current(execution_authorization, policy_time)
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
    result_prefix.verify(context, plan)
    if (
        result_prefix.ledger_root.resolve(strict=False)
        != Path(ledger_root).resolve(strict=False)
    ):
        raise RALValidationError(
            "verified_synthetic_prefix_required",
            "prefix store or ledger root differs from this execution",
        )
    expected_slot_index = len(result_prefix.results) + 1
    predecessor = None if not result_prefix.results else result_prefix.results[-1]
    if (
        request.slot_index != expected_slot_index
        or request.expected_ledger_state["expected_ledger_head"]
        != result_prefix.final_head
        or request.expected_ledger_state["ledger_event_count"]
        != result_prefix.ledger_event_count
        or request.predecessor_receipt_ref
        != (None if predecessor is None else predecessor.result_id)
        or request.predecessor_receipt_digest
        != (None if predecessor is None else predecessor.digest)
    ):
        raise RALValidationError(
            "wave_predecessor_missing",
            "slot request does not immediately extend the durable synthetic prefix",
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
    canonical_authority = application_authority.authority
    verified_attestation_refs = application_authority.attestation_refs
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
    result_prefix.store.put_slot_request(str(request.slot_id), request)
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
    status_digest = sha256_ref(status_view)
    material = {
        "candidate_capability_digest": candidate.verification_digest,
        "wave_plan_digest": plan.digest,
        "slot_request_digest": request.digest,
        "execution_authorization_digest": execution_authorization.verification_digest,
        "result_prefix_digest": result_prefix.verification_digest,
        "application_authority_capability_digest": application_authority.verification_digest,
        "ctcl_receipt_digest": sha256_ref(dict(ctcl_receipt)),
        "registrar_plan_digest": registrar_plan.digest,
        "policy_status_digest": status_digest,
        "planning_time_digest": policy_time.verification_digest,
    }
    return PlannedWaveSlot(
        candidate=candidate,
        wave_plan=plan,
        slot_request=request,
        execution_authorization=execution_authorization,
        result_prefix=result_prefix,
        policy_context=policy_context,
        policy_storage=policy_storage,
        policy_time=policy_time,
        application_authority=application_authority,
        ctcl_receipt=dict(ctcl_receipt),
        ledger_root=Path(ledger_root),
        staging_parent=Path(staging_parent),
        decision=decision,
        registrar_plan=registrar_plan,
        policy_status_digest=status_digest,
        planning_time_digest=policy_time.verification_digest,
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
    *,
    time: VerifiedAuthorityTimeEvidence,
) -> SyntheticWaveSlotExecutionResult:
    if not isinstance(planned, PlannedWaveSlot):
        raise RALValidationError(
            "planned_wave_slot_required", "simulate requires planned slot capability"
        )
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "slot execution requires fresh verified time",
        )
    if store.root.resolve(strict=False) != planned.result_prefix.store.root.resolve(
        strict=False
    ):
        raise RALValidationError(
            "verified_synthetic_prefix_required",
            "execution store differs from the planned result prefix",
        )
    planned.verify_static()
    planned.execution_authorization.verify_current(time)
    planned.application_authority.verify_current(
        planned.execution_authorization, time
    )
    current_status = registration_wave_status(
        planned.policy_context, planned.policy_storage, time
    )
    require_wave_execution(current_status)
    existing = store.get_slot_result(str(planned.slot_request.slot_id))
    if existing is not None:
        current_prefix = verify_synthetic_wave_result_prefix(
            context, planned.wave_plan, store, planned.ledger_root
        )
        if (
            len(current_prefix.results) != planned.slot_request.slot_index
            or current_prefix.results[-1].to_dict() != existing.to_dict()
            or existing.slot_request_digest != planned.slot_request.digest
            or existing.execution_authorization_digest
            != planned.execution_authorization.authorization.digest
        ):
            raise RALValidationError(
                "wave_slot_result_mismatch",
                "existing synthetic result does not match the planned slot",
            )
        return existing
    planned.verify(context, time)
    context.verify_before_io("slot_commit", planned.ledger_root)
    receipt = commit_admission_plan(
        planned.ledger_root,
        planned.registrar_plan,
        planned.candidate.prepared,
        planned.decision,
        planned.application_authority.authority,
        planned.ctcl_receipt,
        verified_attestation_refs=planned.application_authority.attestation_refs,
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
    verified_result = issue_verified_synthetic_slot_result(
        result,
        planned.candidate,
        planned.execution_authorization,
        planned.application_authority,
        planned_slot_digest=planned.plan_digest,
        ctcl_receipt_digest=sha256_ref(planned.ctcl_receipt),
        registrar_plan_digest=planned.registrar_plan.digest,
        policy_status_digest=planned.policy_status_digest,
        prefix_plan_digest=planned.result_prefix.plan_digest,
        prefix_verification_digest=planned.result_prefix.verification_digest,
        prefix_result_digests=tuple(
            value.digest for value in planned.result_prefix.results
        ),
        prefix_final_head=planned.result_prefix.final_head,
        prefix_event_count=planned.result_prefix.ledger_event_count,
        ledger_events=events,
        time=time,
    )
    stored = store.put_slot_result(
        str(planned.slot_request.slot_id), verified_result
    )
    if receipt.committed:
        for event_id in receipt.event_ids:
            context.journal.record("synthetic_ledger_writes", f"ledger-event:{event_id}")
    if stored.kind == "created":
        context.journal.record("synthetic_receipt_writes", str(result.result_id))
    return result
