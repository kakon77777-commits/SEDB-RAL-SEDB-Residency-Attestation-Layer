from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .projection import project_events
from .registration import PreparedRegistration
from .registration_wave_authority import (
    AuthorityTimeEvidence,
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedApplicationApproval,
    VerifiedApplicationAuthority,
    VerifiedAuthorityTimeEvidence,
    VerifiedSlotExecutionAuthorization,
    _verify_user_item,
    derive_verified_application_authority,
    observe_synthetic_authority_time,
    verify_application_approval,
    verify_authority_time_evidence,
    verify_slot_execution_authorization,
)
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_intake import (
    RawApplicantItemSnapshot,
    VerifiedPreparedCandidate,
    verify_applicant_item_evidence,
    verify_prepared_candidate_bindings,
)
from .registration_wave_models import (
    ApplicantItemEvidence,
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    RegistrationWavePolicy,
    RegistrationWavePreparedCandidate,
    SlotExecutionAuthorization,
    SyntheticWaveSlotExecutionResult,
    SyntheticWaveSlotRecoveryResult,
    WaveHostObservation,
    WaveSlotRecoveryAuthorization,
    WaveSlotRequest,
)

_KINDS = (
    "claims",
    "item-evidence",
    "host-observations",
    "candidates",
    "approvals",
    "slot-requests",
    "slot-results",
    "recovery-results",
)
_SLOT_RESULT_CAPABILITY_TOKEN = object()
_RECOVERY_RESULT_CAPABILITY_TOKEN = object()


@dataclass(frozen=True)
class StoreResult:
    kind: Literal["created", "duplicate"]
    relative_ref: str
    record_digest: str


@dataclass(frozen=True)
class VerifiedSyntheticWaveSlotResult:
    result: SyntheticWaveSlotExecutionResult
    candidate: VerifiedPreparedCandidate
    execution: VerifiedSlotExecutionAuthorization
    application_authority: VerifiedApplicationAuthority
    planned_slot_digest: str
    ctcl_receipt_digest: str
    registrar_plan_digest: str
    policy_status_digest: str
    prefix_plan_digest: str
    prefix_verification_digest: str
    prefix_result_digests: tuple[str, ...]
    prefix_final_head: str | None
    prefix_event_count: int
    ledger_events: tuple[dict[str, object], ...]
    issuance_time: VerifiedAuthorityTimeEvidence
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _SLOT_RESULT_CAPABILITY_TOKEN:
            raise RALValidationError(
                "verified_synthetic_result_required",
                "synthetic result capability was not verifier-issued",
            )

    def verify(self) -> None:
        self.candidate.verify()
        self.execution.verify_current(self.issuance_time)
        self.application_authority.verify_current(
            self.execution, self.issuance_time
        )
        result = SyntheticWaveSlotExecutionResult.from_dict(self.result.to_dict())
        request = self.execution.request
        events = tuple(self.ledger_events)
        appended = tuple(result.appended_events)
        suffix = events[self.prefix_event_count :]
        observed_pairs = tuple(
            {
                "event_ref": str(value["event_id"]),
                "event_digest": sha256_ref(value),
            }
            for value in suffix
        )
        projection = project_events(events)
        application = self.execution.approval.application
        application_id = str(application["application_id"])
        resident_id = str(application["claimed_resident_id"])
        instance_id = str(application["instance_claims"][0]["instance_id"])
        address_id = str(application["addresses"][0]["address_id"])
        resident = projection.residents[resident_id]
        instance = next(
            value
            for value in resident["instances"]
            if value["instance_id"] == instance_id
        )
        address = next(
            value
            for value in resident["addresses"]
            if value["address_id"] == address_id
        )
        expected_projection_digests = {
            "application": sha256_ref(projection.applications[application_id]),
            "resident": sha256_ref(resident),
            "instance": sha256_ref(instance),
            "address": sha256_ref(address),
            "binding": sha256_ref(projection.directory[resident_id]),
        }
        planned_material = {
            "candidate_capability_digest": self.candidate.verification_digest,
            "wave_plan_digest": self.execution.plan.digest,
            "slot_request_digest": request.digest,
            "execution_authorization_digest": self.execution.verification_digest,
            "result_prefix_digest": self.prefix_verification_digest,
            "application_authority_capability_digest": self.application_authority.verification_digest,
            "ctcl_receipt_digest": self.ctcl_receipt_digest,
            "registrar_plan_digest": self.registrar_plan_digest,
            "policy_status_digest": self.policy_status_digest,
            "planning_time_digest": self.issuance_time.verification_digest,
        }
        material = {
            "result_digest": result.digest,
            "candidate_capability_digest": self.candidate.verification_digest,
            "execution_capability_digest": self.execution.verification_digest,
            "application_authority_capability_digest": self.application_authority.verification_digest,
            "planned_slot_digest": self.planned_slot_digest,
            "ledger_events_digest": sha256_ref(list(events)),
            "prefix_plan_digest": self.prefix_plan_digest,
            "prefix_verification_digest": self.prefix_verification_digest,
            "prefix_result_digests": list(self.prefix_result_digests),
            "prefix_final_head": self.prefix_final_head,
            "prefix_event_count": self.prefix_event_count,
            "issuance_time_digest": self.issuance_time.verification_digest,
        }
        if (
            self.planned_slot_digest != sha256_ref(planned_material)
            or request.candidate_digest != self.candidate.digest
            or request.application_digest != self.candidate.application_digest
            or self.candidate.application_digest
            != self.execution.approval.application_digest
            or result.wave_plan_digest != self.prefix_plan_digest
            or result.wave_plan_ref
            != f"registration-wave-plan:{self.execution.plan.wave_id}"
            or result.result_id != f"synthetic-slot-result:{result.slot_index}"
            or result.slot_id != request.slot_id
            or result.slot_index != request.slot_index
            or result.slot_request_ref != request.request_id
            or result.slot_request_digest != request.digest
            or result.execution_authorization_ref
            != self.execution.authorization.execution_authorization_id
            or result.execution_authorization_digest
            != self.execution.authorization.digest
            or result.application_approval_ref
            != self.execution.approval.approval.approval_id
            or result.application_approval_digest
            != self.execution.approval.approval.digest
            or result.pre_head != self.prefix_final_head
            or result.slot_index != len(self.prefix_result_digests) + 1
            or request.expected_ledger_state["ledger_event_count"]
            != self.prefix_event_count
            or len(events) != self.prefix_event_count + len(appended)
            or not suffix
            or tuple(appended) != observed_pairs
            or result.post_head != suffix[-1]["integrity"]["chain_digest"]
            or result.projection_digests != expected_projection_digests
            or result.execution_scope != "synthetic"
            or result.production_wave_run != "NOT_RUN"
            or result.live_limen_b6a != "NOT_RUN"
            or list(result.not_claimed)
            != ["production_admission", "live_limen_resolution"]
            or self.verification_digest != sha256_ref(material)
        ):
            raise RALValidationError(
                "verified_synthetic_result_required",
                "synthetic result authority or prefix evidence differs",
            )


def issue_verified_synthetic_slot_result(
    result: SyntheticWaveSlotExecutionResult,
    candidate: VerifiedPreparedCandidate,
    execution: VerifiedSlotExecutionAuthorization,
    application_authority: VerifiedApplicationAuthority,
    *,
    planned_slot_digest: str,
    ctcl_receipt_digest: str,
    registrar_plan_digest: str,
    policy_status_digest: str,
    prefix_plan_digest: str,
    prefix_verification_digest: str,
    prefix_result_digests: tuple[str, ...],
    prefix_final_head: str | None,
    prefix_event_count: int,
    ledger_events: tuple[dict[str, object], ...],
    time: VerifiedAuthorityTimeEvidence,
) -> VerifiedSyntheticWaveSlotResult:
    material = {
        "result_digest": result.digest,
        "candidate_capability_digest": candidate.verification_digest,
        "execution_capability_digest": execution.verification_digest,
        "application_authority_capability_digest": application_authority.verification_digest,
        "planned_slot_digest": planned_slot_digest,
        "ledger_events_digest": sha256_ref(list(ledger_events)),
        "prefix_plan_digest": prefix_plan_digest,
        "prefix_verification_digest": prefix_verification_digest,
        "prefix_result_digests": list(prefix_result_digests),
        "prefix_final_head": prefix_final_head,
        "prefix_event_count": prefix_event_count,
        "issuance_time_digest": time.verification_digest,
    }
    capability = VerifiedSyntheticWaveSlotResult(
        result=result,
        candidate=candidate,
        execution=execution,
        application_authority=application_authority,
        planned_slot_digest=planned_slot_digest,
        ctcl_receipt_digest=ctcl_receipt_digest,
        registrar_plan_digest=registrar_plan_digest,
        policy_status_digest=policy_status_digest,
        prefix_plan_digest=prefix_plan_digest,
        prefix_verification_digest=prefix_verification_digest,
        prefix_result_digests=prefix_result_digests,
        prefix_final_head=prefix_final_head,
        prefix_event_count=prefix_event_count,
        ledger_events=ledger_events,
        issuance_time=time,
        verification_digest=sha256_ref(material),
        _token=_SLOT_RESULT_CAPABILITY_TOKEN,
    )
    capability.verify()
    return capability


@dataclass(frozen=True)
class VerifiedSyntheticWaveRecoveryResult:
    result: SyntheticWaveSlotRecoveryResult
    recovery_authorization: WaveSlotRecoveryAuthorization
    recovery_raw_item: RawPrincipalItemSnapshot = field(repr=False)
    recovery_host: PrincipalHostObservation
    recovery_time: VerifiedAuthorityTimeEvidence
    recovery_inspection_digest: str
    recovery_planned_slot_digest: str
    recovery_capability_digest: str
    reconstructed_result: VerifiedSyntheticWaveSlotResult
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _RECOVERY_RESULT_CAPABILITY_TOKEN:
            raise RALValidationError(
                "verified_synthetic_recovery_required",
                "synthetic recovery capability was not verifier-issued",
            )

    def verify(self) -> None:
        self.reconstructed_result.verify()
        self.recovery_host.verify()
        self.recovery_time.verify_current(
            self.recovery_authorization.valid_from_ref,
            self.recovery_authorization.expires_at_ref,
        )
        execution = self.reconstructed_result.execution
        plan = execution.plan
        request = execution.request
        expected_intent = {
            "schema": "sedb-ral.registration-wave-slot-recovery-intent/0.1",
            "principal_ref": self.recovery_authorization.principal_ref,
            "wave_plan_digest": plan.digest,
            "slot_id": request.slot_id,
            "slot_request_digest": request.digest,
            "original_execution_authorization_digest": execution.authorization.digest,
            "application_approval_digest": execution.approval.approval.digest,
            "verified_prefix_digest": self.recovery_authorization.verified_prefix_digest,
            "pre_head": request.expected_ledger_state["expected_ledger_head"],
            "post_head": self.result.post_head,
            "checkpoint_digest": plan.checkpoint_digest,
            "current_readback_digest": self.recovery_authorization.current_readback_digest,
        }
        _verify_user_item(
            self.recovery_raw_item, self.recovery_host, expected_intent
        )
        recovery_material = {
            "authorization_digest": self.recovery_authorization.digest,
            "inspection_digest": self.recovery_inspection_digest,
            "planned_slot_digest": self.recovery_planned_slot_digest,
            "raw_item_digest": self.recovery_raw_item.evidence_digest,
            "host_observation_digest": self.recovery_host.digest,
            "issuance_time_digest": self.recovery_time.verification_digest,
        }
        expected_recovery_planned_digest = sha256_ref(
            {
                "planned_digest": self.reconstructed_result.planned_slot_digest,
                "wave_plan_digest": plan.digest,
                "slot_request_digest": request.digest,
                "execution_authorization_digest": execution.authorization.digest,
                "application_approval_digest": execution.approval.approval.digest,
                "checkpoint_digest": plan.checkpoint_digest,
            }
        )
        material = {
            "result_digest": self.result.digest,
            "recovery_capability_digest": self.recovery_capability_digest,
            "reconstructed_result_capability_digest": self.reconstructed_result.verification_digest,
            "recovery_time_digest": self.recovery_time.verification_digest,
        }
        if (
            self.recovery_capability_digest != sha256_ref(recovery_material)
            or self.recovery_authorization.principal_ref
            != execution.approval.approval.principal_ref
            or self.recovery_authorization.wave_plan_digest != plan.digest
            or self.recovery_authorization.slot_request_digest != request.digest
            or self.recovery_authorization.original_execution_authorization_digest
            != execution.authorization.digest
            or self.recovery_authorization.application_approval_digest
            != execution.approval.approval.digest
            or self.recovery_authorization.checkpoint_digest
            != plan.checkpoint_digest
            or self.recovery_planned_slot_digest
            != expected_recovery_planned_digest
            or self.recovery_authorization.source_user_item_digest
            != self.recovery_raw_item.evidence_digest
            or self.recovery_authorization.host_observation_digest
            != self.recovery_host.digest
            or self.result.recovery_authorization_ref
            != self.recovery_authorization.recovery_authorization_id
            or self.result.recovery_authorization_digest
            != self.recovery_authorization.digest
            or self.result.verified_prefix_digest
            != self.recovery_authorization.verified_prefix_digest
            or self.result.reconstructed_result_ref
            != self.reconstructed_result.result.result_id
            or self.result.reconstructed_result_digest
            != self.reconstructed_result.result.digest
            or self.result.pre_head
            != request.expected_ledger_state["expected_ledger_head"]
            or self.verification_digest != sha256_ref(material)
        ):
            raise RALValidationError(
                "verified_synthetic_recovery_required",
                "synthetic recovery authority or result evidence differs",
            )


def issue_verified_synthetic_recovery_result(
    result: SyntheticWaveSlotRecoveryResult,
    *,
    recovery_authorization: WaveSlotRecoveryAuthorization,
    recovery_raw_item: RawPrincipalItemSnapshot,
    recovery_host: PrincipalHostObservation,
    recovery_time: VerifiedAuthorityTimeEvidence,
    recovery_inspection_digest: str,
    recovery_planned_slot_digest: str,
    recovery_capability_digest: str,
    reconstructed_result: VerifiedSyntheticWaveSlotResult,
) -> VerifiedSyntheticWaveRecoveryResult:
    material = {
        "result_digest": result.digest,
        "recovery_capability_digest": recovery_capability_digest,
        "reconstructed_result_capability_digest": reconstructed_result.verification_digest,
        "recovery_time_digest": recovery_time.verification_digest,
    }
    capability = VerifiedSyntheticWaveRecoveryResult(
        result=result,
        recovery_authorization=recovery_authorization,
        recovery_raw_item=recovery_raw_item,
        recovery_host=recovery_host,
        recovery_time=recovery_time,
        recovery_inspection_digest=recovery_inspection_digest,
        recovery_planned_slot_digest=recovery_planned_slot_digest,
        recovery_capability_digest=recovery_capability_digest,
        reconstructed_result=reconstructed_result,
        verification_digest=sha256_ref(material),
        _token=_RECOVERY_RESULT_CAPABILITY_TOKEN,
    )
    capability.verify()
    return capability


def _token(kind: str, identifier: str) -> str:
    return sha256_ref({"kind": kind, "identifier": identifier}).rsplit(":", 1)[-1][:32]


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(code, "Wave store JSON cannot be read") from error
    if not isinstance(value, dict):
        raise RALValidationError(code, "Wave store JSON must be an object")
    return value


def _write_new(path: Path, value: dict[str, object]) -> bool:
    try:
        with path.open("xb") as stream:
            stream.write(canonical_bytes(value))
    except FileExistsError:
        return False
    return True


def _verify_bound(value: dict[str, object], field: str, code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(code, "Wave store digest differs")


def _closed_evidence(material: dict[str, object]) -> dict[str, object]:
    return {**material, "evidence_digest": sha256_ref(material)}


def _verify_closed_evidence(value: object, schema: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RALValidationError(
            "wave_store_capability_invalid", "capability evidence is absent"
        )
    material = dict(value)
    actual = material.pop("evidence_digest", None)
    if material.get("schema") != schema or actual != sha256_ref(material):
        raise RALValidationError(
            "wave_store_capability_invalid", "capability evidence digest differs"
        )
    return value


def _applicant_raw_value(raw: RawApplicantItemSnapshot) -> dict[str, object]:
    content = loads_strict(raw.content_bytes.decode("utf-8"))
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
        "content": content,
    }


def _candidate_capability_evidence(
    candidate: VerifiedPreparedCandidate,
) -> dict[str, object]:
    candidate.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-prepared-candidate-evidence/0.1",
            "claim": loads_strict(
                candidate.verified_item.raw_item.content_bytes.decode("utf-8")
            ),
            "item": candidate.verified_item.item.to_dict(),
            "host": candidate.verified_item.host.to_dict(),
            "raw_item": _applicant_raw_value(candidate.verified_item.raw_item),
            "compatibility_host_v01": candidate.compatibility_host_v01,
            "prepared": candidate.prepared.to_dict(),
        }
    )


def _rebuild_candidate_capability(
    candidate_value: dict[str, object], evidence_value: object
) -> VerifiedPreparedCandidate:
    evidence = _verify_closed_evidence(
        evidence_value, "sedb-ral.verified-prepared-candidate-evidence/0.1"
    )
    raw_value = evidence.get("raw_item")
    if not isinstance(raw_value, dict) or not isinstance(
        raw_value.get("content"), dict
    ):
        raise RALValidationError(
            "wave_store_capability_invalid", "candidate raw evidence differs"
        )
    try:
        raw = RawApplicantItemSnapshot(
            provider=str(raw_value["provider"]),
            adapter_kind=str(raw_value["adapter_kind"]),
            native_thread_id=str(raw_value["native_thread_id"]),
            native_turn_id=str(raw_value["native_turn_id"]),
            source_item_role=str(raw_value["source_item_role"]),
            source_item_kind=str(raw_value["source_item_kind"]),
            source_item_status=str(raw_value["source_item_status"]),
            source_item_parent_thread_id=str(
                raw_value["source_item_parent_thread_id"]
            ),
            source_item_parent_turn_id=str(raw_value["source_item_parent_turn_id"]),
            applicant_item_ref=str(raw_value["applicant_item_ref"]),
            content_bytes=canonical_bytes(raw_value["content"]),
        )
        verified_item = verify_applicant_item_evidence(
            evidence["claim"], evidence["item"], evidence["host"], raw
        )
        return verify_prepared_candidate_bindings(
            candidate_value,
            verified_item=verified_item,
            compatibility_host_v01=evidence["compatibility_host_v01"],
            prepared=PreparedRegistration.from_dict(evidence["prepared"]),
        )
    except (KeyError, TypeError, UnicodeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code == "wave_store_capability_invalid":
            raise
        raise RALValidationError(
            "wave_store_capability_invalid", "candidate capability cannot be rebuilt"
        ) from error


def _principal_raw_value(raw: RawPrincipalItemSnapshot) -> dict[str, object]:
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


def _principal_host_value(host: PrincipalHostObservation) -> dict[str, object]:
    return {
        "provider": host.provider,
        "adapter_kind": host.adapter_kind,
        "native_thread_id": host.native_thread_id,
        "native_turn_id": host.native_turn_id,
        "source_item_role": host.source_item_role,
        "source_item_kind": host.source_item_kind,
        "source_item_status": host.source_item_status,
        "source_item_ref": host.source_item_ref,
        "observed_origin": host.observed_origin,
        "observed_at_ref": host.observed_at_ref,
        "observation_ref": host.observation_ref,
        "digest": host.digest,
    }


def _time_value(time: object) -> dict[str, object]:
    evidence = time.evidence
    return {
        **evidence._source_material(),
        "source_digest": evidence.source_digest,
        "clock_source_digest": time.clock_observation.clock_source_digest,
        "clock_observation_digest": time.clock_observation.observation_digest,
        "verification_digest": time.verification_digest,
    }


def _approval_capability_evidence(
    approval: VerifiedApplicationApproval,
) -> dict[str, object]:
    approval.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-application-approval-evidence/0.1",
            "application": approval.application,
            "raw_item": _principal_raw_value(approval.raw_item),
            "host": _principal_host_value(approval.host),
            "issuance_time": _time_value(approval.issuance_time),
        }
    )


def _rebuild_approval_capability(
    approval_value: dict[str, object], evidence_value: object
) -> VerifiedApplicationApproval:
    evidence = _verify_closed_evidence(
        evidence_value, "sedb-ral.verified-application-approval-evidence/0.1"
    )
    raw_value = evidence.get("raw_item")
    host_value = evidence.get("host")
    time_value = evidence.get("issuance_time")
    if not all(isinstance(value, dict) for value in (raw_value, host_value, time_value)):
        raise RALValidationError(
            "wave_store_capability_invalid", "approval evidence is incomplete"
        )
    try:
        raw = RawPrincipalItemSnapshot(
            provider=str(raw_value["provider"]),
            adapter_kind=str(raw_value["adapter_kind"]),
            native_thread_id=str(raw_value["native_thread_id"]),
            native_turn_id=str(raw_value["native_turn_id"]),
            source_item_role=str(raw_value["source_item_role"]),
            source_item_kind=str(raw_value["source_item_kind"]),
            source_item_status=str(raw_value["source_item_status"]),
            source_item_parent_thread_id=str(
                raw_value["source_item_parent_thread_id"]
            ),
            source_item_parent_turn_id=str(raw_value["source_item_parent_turn_id"]),
            source_item_ref=str(raw_value["source_item_ref"]),
            content_bytes=canonical_bytes(raw_value["content"]),
        )
        host = PrincipalHostObservation(
            provider=str(host_value["provider"]),
            adapter_kind=str(host_value["adapter_kind"]),
            native_thread_id=str(host_value["native_thread_id"]),
            native_turn_id=str(host_value["native_turn_id"]),
            source_item_role=str(host_value["source_item_role"]),
            source_item_kind=str(host_value["source_item_kind"]),
            source_item_status=str(host_value["source_item_status"]),
            source_item_ref=str(host_value["source_item_ref"]),
            observed_origin=str(host_value["observed_origin"]),
            observed_at_ref=str(host_value["observed_at_ref"]),
            observation_ref=str(host_value["observation_ref"]),
            digest=str(host_value["digest"]),
        )
        raw_time = AuthorityTimeEvidence(
            now_ref=str(time_value["now_ref"]),
            now_epoch_ns=time_value["now_epoch_ns"],
            valid_from_ref=str(time_value["valid_from_ref"]),
            valid_from_epoch_ns=time_value["valid_from_epoch_ns"],
            expires_at_ref=time_value["expires_at_ref"],
            expires_at_epoch_ns=time_value["expires_at_epoch_ns"],
            source_ref=str(time_value["source_ref"]),
            source_digest=str(time_value["source_digest"]),
        )
        raw_time.verify_source()
        clock_observation = observe_synthetic_authority_time(
            now_ref=raw_time.now_ref,
            now_epoch_ns=raw_time.now_epoch_ns,
            valid_from_ref=raw_time.valid_from_ref,
            valid_from_epoch_ns=raw_time.valid_from_epoch_ns,
            expires_at_ref=raw_time.expires_at_ref,
            expires_at_epoch_ns=raw_time.expires_at_epoch_ns,
        )
        verified_time = verify_authority_time_evidence(clock_observation)
        if (
            raw_time != clock_observation.evidence
            or clock_observation.clock_source_digest
            != time_value["clock_source_digest"]
            or clock_observation.observation_digest
            != time_value["clock_observation_digest"]
            or verified_time.verification_digest
            != time_value["verification_digest"]
        ):
            raise RALValidationError(
                "wave_store_capability_invalid", "approval time capability differs"
            )
        approval = PrincipalApplicationApproval.from_dict(approval_value)
        return verify_application_approval(
            approval,
            evidence["application"],
            raw,
            host,
            expected_principal_ref=str(approval.principal_ref),
            time=verified_time,
        )
    except (KeyError, TypeError, UnicodeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code == "wave_store_capability_invalid":
            raise
        raise RALValidationError(
            "wave_store_capability_invalid", "approval capability cannot be rebuilt"
        ) from error


def _execution_capability_evidence(
    execution: VerifiedSlotExecutionAuthorization,
) -> dict[str, object]:
    execution.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-slot-execution-evidence/0.1",
            "authorization": execution.authorization.to_dict(),
            "approval": execution.approval.approval.to_dict(),
            "approval_capability": _approval_capability_evidence(
                execution.approval
            ),
            "plan": execution.plan.to_dict(),
            "request": execution.request.to_dict(),
            "policy": execution.policy.to_dict(),
            "checkpoint": execution.checkpoint,
            "current_status": execution.current_status,
            "raw_item": _principal_raw_value(execution.raw_item),
            "host": _principal_host_value(execution.host),
            "issuance_time": _time_value(execution.issuance_time),
        }
    )


def _rebuild_time_capability(time_value: object):
    if not isinstance(time_value, dict):
        raise RALValidationError(
            "wave_store_capability_invalid", "time capability evidence is absent"
        )
    try:
        raw_time = AuthorityTimeEvidence(
            now_ref=str(time_value["now_ref"]),
            now_epoch_ns=time_value["now_epoch_ns"],
            valid_from_ref=str(time_value["valid_from_ref"]),
            valid_from_epoch_ns=time_value["valid_from_epoch_ns"],
            expires_at_ref=time_value["expires_at_ref"],
            expires_at_epoch_ns=time_value["expires_at_epoch_ns"],
            source_ref=str(time_value["source_ref"]),
            source_digest=str(time_value["source_digest"]),
        )
        raw_time.verify_source()
        clock_observation = observe_synthetic_authority_time(
            now_ref=raw_time.now_ref,
            now_epoch_ns=raw_time.now_epoch_ns,
            valid_from_ref=raw_time.valid_from_ref,
            valid_from_epoch_ns=raw_time.valid_from_epoch_ns,
            expires_at_ref=raw_time.expires_at_ref,
            expires_at_epoch_ns=raw_time.expires_at_epoch_ns,
        )
        verified_time = verify_authority_time_evidence(clock_observation)
        if (
            raw_time != clock_observation.evidence
            or clock_observation.clock_source_digest
            != time_value["clock_source_digest"]
            or clock_observation.observation_digest
            != time_value["clock_observation_digest"]
            or verified_time.verification_digest
            != time_value["verification_digest"]
        ):
            raise RALValidationError(
                "wave_store_capability_invalid", "time capability differs"
            )
        return verified_time
    except (KeyError, TypeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code == "wave_store_capability_invalid":
            raise
        raise RALValidationError(
            "wave_store_capability_invalid", "time capability cannot be rebuilt"
        ) from error


def _rebuild_principal_raw(raw_value: object) -> RawPrincipalItemSnapshot:
    if not isinstance(raw_value, dict):
        raise RALValidationError(
            "wave_store_capability_invalid", "principal raw evidence is absent"
        )
    try:
        return RawPrincipalItemSnapshot(
            provider=str(raw_value["provider"]),
            adapter_kind=str(raw_value["adapter_kind"]),
            native_thread_id=str(raw_value["native_thread_id"]),
            native_turn_id=str(raw_value["native_turn_id"]),
            source_item_role=str(raw_value["source_item_role"]),
            source_item_kind=str(raw_value["source_item_kind"]),
            source_item_status=str(raw_value["source_item_status"]),
            source_item_parent_thread_id=str(
                raw_value["source_item_parent_thread_id"]
            ),
            source_item_parent_turn_id=str(raw_value["source_item_parent_turn_id"]),
            source_item_ref=str(raw_value["source_item_ref"]),
            content_bytes=canonical_bytes(raw_value["content"]),
        )
    except (KeyError, TypeError) as error:
        raise RALValidationError(
            "wave_store_capability_invalid", "principal raw evidence differs"
        ) from error


def _rebuild_principal_host(host_value: object) -> PrincipalHostObservation:
    if not isinstance(host_value, dict):
        raise RALValidationError(
            "wave_store_capability_invalid", "principal host evidence is absent"
        )
    try:
        host = PrincipalHostObservation(
            provider=str(host_value["provider"]),
            adapter_kind=str(host_value["adapter_kind"]),
            native_thread_id=str(host_value["native_thread_id"]),
            native_turn_id=str(host_value["native_turn_id"]),
            source_item_role=str(host_value["source_item_role"]),
            source_item_kind=str(host_value["source_item_kind"]),
            source_item_status=str(host_value["source_item_status"]),
            source_item_ref=str(host_value["source_item_ref"]),
            observed_origin=str(host_value["observed_origin"]),
            observed_at_ref=str(host_value["observed_at_ref"]),
            observation_ref=str(host_value["observation_ref"]),
            digest=str(host_value["digest"]),
        )
        host.verify()
        return host
    except (KeyError, TypeError, RALValidationError) as error:
        raise RALValidationError(
            "wave_store_capability_invalid", "principal host evidence differs"
        ) from error


def _rebuild_execution_capability(
    evidence_value: object,
) -> VerifiedSlotExecutionAuthorization:
    evidence = _verify_closed_evidence(
        evidence_value, "sedb-ral.verified-slot-execution-evidence/0.1"
    )
    try:
        approval = _rebuild_approval_capability(
            evidence["approval"], evidence["approval_capability"]
        )
        authorization = SlotExecutionAuthorization.from_dict(
            evidence["authorization"]
        )
        plan = RegistrationWavePlan.from_dict(evidence["plan"])
        request = WaveSlotRequest.from_dict(evidence["request"])
        policy = RegistrationWavePolicy.from_dict(evidence["policy"])
        raw = _rebuild_principal_raw(evidence["raw_item"])
        host = _rebuild_principal_host(evidence["host"])
        time = _rebuild_time_capability(evidence["issuance_time"])
        return verify_slot_execution_authorization(
            authorization,
            plan,
            request,
            approval,
            policy,
            evidence["checkpoint"],
            evidence["current_status"],
            raw,
            host,
            expected_principal_ref=str(authorization.principal_ref),
            time=time,
        )
    except (KeyError, TypeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code == "wave_store_capability_invalid":
            raise
        raise RALValidationError(
            "wave_store_capability_invalid", "JIT capability cannot be rebuilt"
        ) from error


def _slot_result_capability_evidence(
    capability: VerifiedSyntheticWaveSlotResult,
) -> dict[str, object]:
    capability.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-synthetic-slot-result-evidence/0.1",
            "candidate": capability.candidate.to_dict(),
            "candidate_capability": _candidate_capability_evidence(
                capability.candidate
            ),
            "execution_capability": _execution_capability_evidence(
                capability.execution
            ),
            "application_authority": capability.application_authority.authority,
            "application_authority_attestations": sorted(
                capability.application_authority.attestation_refs
            ),
            "application_authority_capability_digest": capability.application_authority.verification_digest,
            "planned_slot_digest": capability.planned_slot_digest,
            "ctcl_receipt_digest": capability.ctcl_receipt_digest,
            "registrar_plan_digest": capability.registrar_plan_digest,
            "policy_status_digest": capability.policy_status_digest,
            "prefix_plan_digest": capability.prefix_plan_digest,
            "prefix_verification_digest": capability.prefix_verification_digest,
            "prefix_result_digests": list(capability.prefix_result_digests),
            "prefix_final_head": capability.prefix_final_head,
            "prefix_event_count": capability.prefix_event_count,
            "ledger_events": list(capability.ledger_events),
            "issuance_time": _time_value(capability.issuance_time),
        }
    )


def _rebuild_slot_result_capability(
    result_value: dict[str, object], evidence_value: object
) -> VerifiedSyntheticWaveSlotResult:
    evidence = _verify_closed_evidence(
        evidence_value, "sedb-ral.verified-synthetic-slot-result-evidence/0.1"
    )
    try:
        execution = _rebuild_execution_capability(
            evidence["execution_capability"]
        )
        candidate = _rebuild_candidate_capability(
            evidence["candidate"], evidence["candidate_capability"]
        )
        time = _rebuild_time_capability(evidence["issuance_time"])
        authority = derive_verified_application_authority(
            str(execution.approval.application_digest), execution, time
        )
        if (
            authority.authority != evidence["application_authority"]
            or sorted(authority.attestation_refs)
            != evidence["application_authority_attestations"]
            or authority.verification_digest
            != evidence["application_authority_capability_digest"]
        ):
            raise RALValidationError(
                "verified_synthetic_result_required",
                "derived application authority differs",
            )
        return issue_verified_synthetic_slot_result(
            SyntheticWaveSlotExecutionResult.from_dict(result_value),
            candidate,
            execution,
            authority,
            planned_slot_digest=str(evidence["planned_slot_digest"]),
            ctcl_receipt_digest=str(evidence["ctcl_receipt_digest"]),
            registrar_plan_digest=str(evidence["registrar_plan_digest"]),
            policy_status_digest=str(evidence["policy_status_digest"]),
            prefix_plan_digest=str(evidence["prefix_plan_digest"]),
            prefix_verification_digest=str(
                evidence["prefix_verification_digest"]
            ),
            prefix_result_digests=tuple(evidence["prefix_result_digests"]),
            prefix_final_head=evidence["prefix_final_head"],
            prefix_event_count=evidence["prefix_event_count"],
            ledger_events=tuple(evidence["ledger_events"]),
            time=time,
        )
    except (KeyError, TypeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code in {
            "wave_store_capability_invalid",
            "verified_synthetic_result_required",
        }:
            raise
        raise RALValidationError(
            "verified_synthetic_result_required",
            "synthetic result capability cannot be rebuilt",
        ) from error


def _recovery_result_capability_evidence(
    capability: VerifiedSyntheticWaveRecoveryResult,
) -> dict[str, object]:
    capability.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-synthetic-recovery-result-evidence/0.1",
            "recovery_authorization": capability.recovery_authorization.to_dict(),
            "recovery_raw_item": _principal_raw_value(
                capability.recovery_raw_item
            ),
            "recovery_host": _principal_host_value(capability.recovery_host),
            "recovery_time": _time_value(capability.recovery_time),
            "recovery_inspection_digest": capability.recovery_inspection_digest,
            "recovery_planned_slot_digest": capability.recovery_planned_slot_digest,
            "recovery_capability_digest": capability.recovery_capability_digest,
            "reconstructed_result": capability.reconstructed_result.result.to_dict(),
            "reconstructed_result_capability": _slot_result_capability_evidence(
                capability.reconstructed_result
            ),
        }
    )


def _rebuild_recovery_result_capability(
    result_value: dict[str, object], evidence_value: object
) -> VerifiedSyntheticWaveRecoveryResult:
    evidence = _verify_closed_evidence(
        evidence_value,
        "sedb-ral.verified-synthetic-recovery-result-evidence/0.1",
    )
    try:
        recovery_authorization = WaveSlotRecoveryAuthorization.from_dict(
            evidence["recovery_authorization"]
        )
        reconstructed = _rebuild_slot_result_capability(
            evidence["reconstructed_result"],
            evidence["reconstructed_result_capability"],
        )
        return issue_verified_synthetic_recovery_result(
            SyntheticWaveSlotRecoveryResult.from_dict(result_value),
            recovery_authorization=recovery_authorization,
            recovery_raw_item=_rebuild_principal_raw(
                evidence["recovery_raw_item"]
            ),
            recovery_host=_rebuild_principal_host(evidence["recovery_host"]),
            recovery_time=_rebuild_time_capability(evidence["recovery_time"]),
            recovery_inspection_digest=str(
                evidence["recovery_inspection_digest"]
            ),
            recovery_planned_slot_digest=str(
                evidence["recovery_planned_slot_digest"]
            ),
            recovery_capability_digest=str(
                evidence["recovery_capability_digest"]
            ),
            reconstructed_result=reconstructed,
        )
    except (KeyError, TypeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code in {
            "wave_store_capability_invalid",
            "verified_synthetic_result_required",
            "verified_synthetic_recovery_required",
        }:
            raise
        raise RALValidationError(
            "verified_synthetic_recovery_required",
            "synthetic recovery capability cannot be rebuilt",
        ) from error


class RegistrationWaveStore:
    def __init__(
        self,
        context: SyntheticWaveExecutionContext,
        root: Path,
        expected_wave_digest: str,
    ):
        self.context = context
        self.root = Path(root)
        self.expected_wave_digest = expected_wave_digest
        if self.root.resolve(strict=False) != context.target_root.resolve(strict=False):
            raise RALValidationError(
                "wave_staging_root_refused", "store root differs from context target"
            )
        context.verify_before_io("store_initialize", self.root)
        if self.root.exists():
            if not self.root.is_dir():
                raise RALValidationError(
                    "wave_staging_root_refused", "store root is not a directory"
                )
        else:
            self.root.mkdir(parents=False)
        for kind in _KINDS:
            (self.root / "records" / kind).mkdir(parents=True, exist_ok=True)
        (self.root / "quarantine").mkdir(exist_ok=True)
        manifest_material = {
            "schema": "sedb-ral.registration-wave-store-manifest/0.1",
            "layout_version": "0.1",
            "mode": context.mode.value,
            "expected_wave_digest": expected_wave_digest,
            "record_kinds": list(_KINDS),
            "not_claimed": [
                "canonical_commit",
                "production_registry",
                "private_access",
            ],
        }
        manifest = {
            **manifest_material,
            "manifest_digest": sha256_ref(manifest_material),
        }
        manifest_path = self.root / "STORE-MANIFEST.json"
        context.verify_before_io("store_manifest_write", manifest_path)
        if _write_new(manifest_path, manifest):
            context.record_effect("staging_writes", "wave-store:manifest")
        elif canonical_bytes(_read_object(manifest_path, "wave_store_manifest_invalid")) != canonical_bytes(manifest):
            raise RALValidationError(
                "wave_staging_digest_conflict", "store manifest bytes differ"
            )

    def read_manifest(self) -> dict[str, object]:
        path = self.root / "STORE-MANIFEST.json"
        self.context.verify_before_io("store_manifest_read", path)
        value = _read_object(path, "wave_store_manifest_invalid")
        _verify_bound(value, "manifest_digest", "wave_store_manifest_invalid")
        if (
            value.get("mode") != self.context.mode.value
            or value.get("expected_wave_digest") != self.expected_wave_digest
            or value.get("record_kinds") != list(_KINDS)
        ):
            raise RALValidationError(
                "wave_store_manifest_invalid", "store manifest bindings differ"
            )
        return value

    def _path(self, kind: str, identifier: str) -> Path:
        return self.root / "records" / kind / f"record-{_token(kind, identifier)}.json"

    def _quarantine(
        self,
        *,
        kind: str,
        identifier: str,
        existing_digest: str,
        incoming_digest: str,
    ) -> None:
        material = {
            "schema": "sedb-ral.registration-wave-store-quarantine/0.1",
            "record_kind": kind,
            "record_id_digest": sha256_ref(
                {"kind": kind, "identifier": identifier}
            ),
            "existing_digest": existing_digest,
            "incoming_digest": incoming_digest,
            "error_code": "wave_staging_digest_conflict",
            "not_claimed": ["source_deleted", "conflict_resolved"],
        }
        value = {**material, "quarantine_digest": sha256_ref(material)}
        path = self.root / "quarantine" / (
            f"conflict-{_token(kind, identifier)}-{incoming_digest.rsplit(':', 1)[-1][:16]}.json"
        )
        self.context.verify_before_io("store_quarantine_write", path)
        if _write_new(path, value):
            self.context.record_effect(
                "staging_writes", path.relative_to(self.root).as_posix()
            )

    def _submit(
        self,
        *,
        kind: str,
        identifier: str,
        object_ref: str,
        object_digest: str,
        value: dict[str, object],
        capability_digest: str | None = None,
        capability_evidence: dict[str, object] | None = None,
    ) -> StoreResult:
        if kind not in _KINDS or not identifier:
            raise RALValidationError(
                "wave_store_record_invalid", "store kind or identifier is invalid"
            )
        material = {
            "schema": "sedb-ral.registration-wave-store-record/0.1",
            "record_kind": kind,
            "record_id": identifier,
            "wave_digest": self.expected_wave_digest,
            "object_ref": object_ref,
            "object_digest": object_digest,
            "capability_digest": capability_digest,
            "capability_evidence": capability_evidence,
            "object": value,
        }
        record = {**material, "record_digest": sha256_ref(material)}
        path = self._path(kind, identifier)
        self.context.verify_before_io("store_record_write", path)
        if _write_new(path, record):
            relative = path.relative_to(self.root).as_posix()
            self.context.record_effect("staging_writes", relative)
            return StoreResult("created", relative, str(record["record_digest"]))
        existing = _read_object(path, "wave_store_record_invalid")
        if canonical_bytes(existing) == canonical_bytes(record):
            return StoreResult(
                "duplicate",
                path.relative_to(self.root).as_posix(),
                str(existing["record_digest"]),
            )
        self._quarantine(
            kind=kind,
            identifier=identifier,
            existing_digest=str(existing.get("record_digest", "")),
            incoming_digest=str(record["record_digest"]),
        )
        raise RALValidationError(
            "wave_staging_digest_conflict", "same store ID binds changed bytes"
        )

    def put_claim(self, identifier: str, claim: dict[str, object]) -> StoreResult:
        validate_contract("self-application-claim.schema.json", claim)
        return self._submit(
            kind="claims",
            identifier=identifier,
            object_ref=f"self-application-claim:{identifier}",
            object_digest=sha256_ref(claim),
            value=claim,
        )

    def put_item_evidence(
        self, identifier: str, item: ApplicantItemEvidence
    ) -> StoreResult:
        parsed = ApplicantItemEvidence.from_dict(item.to_dict())
        return self._submit(
            kind="item-evidence",
            identifier=identifier,
            object_ref=str(parsed.item_evidence_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def put_host_observation(
        self, identifier: str, host: WaveHostObservation
    ) -> StoreResult:
        parsed = WaveHostObservation.from_dict(host.to_dict())
        return self._submit(
            kind="host-observations",
            identifier=identifier,
            object_ref=str(parsed.observation_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def put_candidate(
        self, identifier: str, candidate: VerifiedPreparedCandidate
    ) -> StoreResult:
        if not isinstance(candidate, VerifiedPreparedCandidate):
            raise RALValidationError(
                "verified_candidate_required", "store requires verified candidate"
            )
        candidate.verify()
        return self._submit(
            kind="candidates",
            identifier=identifier,
            object_ref=str(candidate.candidate.candidate_id),
            object_digest=candidate.digest,
            value=candidate.to_dict(),
            capability_digest=candidate.verification_digest,
            capability_evidence=_candidate_capability_evidence(candidate),
        )

    def put_approval(
        self, identifier: str, approval: VerifiedApplicationApproval
    ) -> StoreResult:
        if not isinstance(approval, VerifiedApplicationApproval):
            raise RALValidationError(
                "verified_application_approval_required",
                "store requires verified application approval",
            )
        approval.verify()
        return self._submit(
            kind="approvals",
            identifier=identifier,
            object_ref=str(approval.approval.approval_id),
            object_digest=approval.approval.digest,
            value=approval.approval.to_dict(),
            capability_digest=approval.verification_digest,
            capability_evidence=_approval_capability_evidence(approval),
        )

    def put_slot_request(
        self, identifier: str, request: WaveSlotRequest
    ) -> StoreResult:
        parsed = WaveSlotRequest.from_dict(request.to_dict())
        return self._submit(
            kind="slot-requests",
            identifier=identifier,
            object_ref=str(parsed.request_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def get_slot_request(self, identifier: str) -> WaveSlotRequest | None:
        path = self._path("slot-requests", identifier)
        self.context.verify_before_io("store_slot_request_read", path)
        if not path.is_file():
            return None
        record = self._verify_record(path)
        return WaveSlotRequest.from_dict(record["object"])

    def put_slot_result(self, identifier: str, result: object) -> StoreResult:
        if not isinstance(result, VerifiedSyntheticWaveSlotResult):
            if not isinstance(result, SyntheticWaveSlotExecutionResult):
                raise RALValidationError(
                    "synthetic_result_type_required",
                    "production slot receipts cannot enter synthetic store",
                )
            raise RALValidationError(
                "verified_synthetic_result_required",
                "plain self-sealed slot results are not durable capabilities",
            )
        result.verify()
        parsed = SyntheticWaveSlotExecutionResult.from_dict(result.result.to_dict())
        return self._submit(
            kind="slot-results",
            identifier=identifier,
            object_ref=str(parsed.result_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
            capability_digest=result.verification_digest,
            capability_evidence=_slot_result_capability_evidence(result),
        )

    def get_verified_slot_result(
        self, identifier: str
    ) -> VerifiedSyntheticWaveSlotResult | None:
        path = self._path("slot-results", identifier)
        self.context.verify_before_io("store_slot_result_read", path)
        if not path.is_file():
            return None
        record = self._verify_record(path)
        return _rebuild_slot_result_capability(
            record["object"], record["capability_evidence"]
        )

    def get_slot_result(
        self, identifier: str
    ) -> SyntheticWaveSlotExecutionResult | None:
        capability = self.get_verified_slot_result(identifier)
        return None if capability is None else capability.result

    def put_recovery_result(self, identifier: str, result: object) -> StoreResult:
        if not isinstance(result, VerifiedSyntheticWaveRecoveryResult):
            if not isinstance(result, SyntheticWaveSlotRecoveryResult):
                raise RALValidationError(
                    "synthetic_result_type_required",
                    "production recovery receipts cannot enter synthetic store",
                )
            raise RALValidationError(
                "verified_synthetic_recovery_required",
                "plain self-sealed recovery results are not durable capabilities",
            )
        result.verify()
        parsed = SyntheticWaveSlotRecoveryResult.from_dict(result.result.to_dict())
        return self._submit(
            kind="recovery-results",
            identifier=identifier,
            object_ref=str(parsed.result_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
            capability_digest=result.verification_digest,
            capability_evidence=_recovery_result_capability_evidence(result),
        )

    def get_verified_recovery_result(
        self, identifier: str
    ) -> VerifiedSyntheticWaveRecoveryResult | None:
        path = self._path("recovery-results", identifier)
        self.context.verify_before_io("store_recovery_result_read", path)
        if not path.is_file():
            return None
        record = self._verify_record(path)
        return _rebuild_recovery_result_capability(
            record["object"], record["capability_evidence"]
        )

    def get_recovery_result(
        self, identifier: str
    ) -> SyntheticWaveSlotRecoveryResult | None:
        capability = self.get_verified_recovery_result(identifier)
        return None if capability is None else capability.result

    def _verify_record(self, path: Path) -> dict[str, object]:
        value = _read_object(path, "wave_store_record_invalid")
        if set(value) != {
            "schema",
            "record_kind",
            "record_id",
            "wave_digest",
            "object_ref",
            "object_digest",
            "capability_digest",
            "capability_evidence",
            "object",
            "record_digest",
        }:
            raise RALValidationError(
                "wave_store_record_invalid", "record fields differ"
            )
        _verify_bound(value, "record_digest", "wave_store_record_invalid")
        kind = str(value["record_kind"])
        record_id = value["record_id"]
        if (
            not isinstance(record_id, str)
            or not record_id
            or path != self._path(kind, record_id)
        ):
            raise RALValidationError(
                "wave_store_record_path_mismatch",
                "record path does not match its kind and identifier",
            )
        obj = value["object"]
        if not isinstance(obj, dict):
            raise RALValidationError(
                "wave_store_record_invalid", "stored object is not an object"
            )
        parsers = {
            "claims": lambda item: (
                validate_contract("self-application-claim.schema.json", item),
                sha256_ref(item),
            )[1],
            "item-evidence": lambda item: ApplicantItemEvidence.from_dict(item).digest,
            "host-observations": lambda item: WaveHostObservation.from_dict(item).digest,
            "candidates": lambda item: RegistrationWavePreparedCandidate.from_dict(item).digest,
            "approvals": lambda item: PrincipalApplicationApproval.from_dict(item).digest,
            "slot-requests": lambda item: WaveSlotRequest.from_dict(item).digest,
            "slot-results": lambda item: SyntheticWaveSlotExecutionResult.from_dict(item).digest,
            "recovery-results": lambda item: SyntheticWaveSlotRecoveryResult.from_dict(item).digest,
        }
        if kind not in parsers or parsers[kind](obj) != value["object_digest"]:
            raise RALValidationError(
                "wave_store_record_invalid", "stored object digest differs"
            )
        expected_refs = {
            "claims": f"self-application-claim:{record_id}",
            "item-evidence": obj.get("item_evidence_id"),
            "host-observations": obj.get("observation_id"),
            "candidates": obj.get("candidate_id"),
            "approvals": obj.get("approval_id"),
            "slot-requests": obj.get("request_id"),
            "slot-results": obj.get("result_id"),
            "recovery-results": obj.get("result_id"),
        }
        if (
            value["wave_digest"] != self.expected_wave_digest
            or value["object_ref"] != expected_refs[kind]
        ):
            raise RALValidationError(
                "wave_store_record_binding_mismatch",
                "record does not bind this Wave and verified object reference",
            )
        capability_digest = value["capability_digest"]
        capability_evidence = value["capability_evidence"]
        if kind == "candidates":
            rebuilt = _rebuild_candidate_capability(obj, capability_evidence)
            observed_capability_digest = rebuilt.verification_digest
        elif kind == "approvals":
            rebuilt = _rebuild_approval_capability(obj, capability_evidence)
            observed_capability_digest = rebuilt.verification_digest
        elif kind == "slot-results":
            rebuilt = _rebuild_slot_result_capability(obj, capability_evidence)
            observed_capability_digest = rebuilt.verification_digest
        elif kind == "recovery-results":
            rebuilt = _rebuild_recovery_result_capability(obj, capability_evidence)
            observed_capability_digest = rebuilt.verification_digest
        else:
            observed_capability_digest = None
            if capability_evidence is not None:
                raise RALValidationError(
                    "wave_store_capability_invalid",
                    "non-capability record carries capability evidence",
                )
        if capability_digest != observed_capability_digest:
            raise RALValidationError(
                "wave_store_capability_invalid",
                "stored capability digest cannot be re-established",
            )
        return value

    def _verify_quarantine(self, path: Path) -> None:
        value = _read_object(path, "wave_store_quarantine_invalid")
        if set(value) != {
            "schema",
            "record_kind",
            "record_id_digest",
            "existing_digest",
            "incoming_digest",
            "error_code",
            "not_claimed",
            "quarantine_digest",
        }:
            raise RALValidationError(
                "wave_store_quarantine_invalid", "quarantine fields differ"
            )
        _verify_bound(
            value, "quarantine_digest", "wave_store_quarantine_invalid"
        )
        if (
            value["schema"]
            != "sedb-ral.registration-wave-store-quarantine/0.1"
            or value["record_kind"] not in _KINDS
            or value["error_code"] != "wave_staging_digest_conflict"
        ):
            raise RALValidationError(
                "wave_store_quarantine_invalid", "quarantine semantics differ"
            )

    def verify(self) -> dict[str, object]:
        self.context.verify_before_io("store_verify", self.root)
        self.read_manifest()
        expected_dirs = {"records", "quarantine", *{f"records/{kind}" for kind in _KINDS}}
        observed_dirs = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_dir()
        }
        if observed_dirs != expected_dirs:
            raise RALValidationError(
                "wave_store_layout_invalid", "store directories differ"
            )
        observed_files = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        allowed_files = {"STORE-MANIFEST.json"}
        allowed_files.update(
            name
            for name in observed_files
            if any(
                name.startswith(f"records/{kind}/record-")
                and name.endswith(".json")
                for kind in _KINDS
            )
            or (name.startswith("quarantine/conflict-") and name.endswith(".json"))
        )
        if observed_files != allowed_files:
            raise RALValidationError(
                "wave_store_layout_invalid", "store files differ"
            )
        records = [
            self._verify_record(path)
            for path in sorted((self.root / "records").rglob("*.json"))
        ]
        for path in sorted((self.root / "quarantine").glob("*.json")):
            self._verify_quarantine(path)
        inventory = [
            {
                "record_kind": value["record_kind"],
                "object_ref": value["object_ref"],
                "object_digest": value["object_digest"],
                "record_digest": value["record_digest"],
            }
            for value in records
        ]
        return {
            "verified": True,
            "mode": self.context.mode.value,
            "record_count": len(records),
            "inventory_digest": sha256_ref(inventory),
        }
