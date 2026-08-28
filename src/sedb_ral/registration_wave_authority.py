from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .registration_wave_models import (
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    RegistrationWavePolicy,
    SlotExecutionAuthorization,
    WaveSlotRequest,
)

_APPROVAL_TOKEN = object()
_EXECUTION_TOKEN = object()


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("authority value must remain an object")
    return canonical


@dataclass(frozen=True)
class AuthorityTimeEvidence:
    now_ref: str
    now_epoch_ns: int
    valid_from_ref: str
    valid_from_epoch_ns: int
    expires_at_ref: str | None
    expires_at_epoch_ns: int | None
    source_ref: str
    source_digest: str

    def verify(self, valid_from_ref: str, expires_at_ref: str | None) -> None:
        integers = (
            self.now_epoch_ns,
            self.valid_from_epoch_ns,
            self.expires_at_epoch_ns,
        )
        if any(
            value is not None and (not isinstance(value, int) or isinstance(value, bool))
            for value in integers
        ):
            raise RALValidationError(
                "authority_time_invalid", "authority time evidence is not integral"
            )
        if (
            self.valid_from_ref != valid_from_ref
            or self.expires_at_ref != expires_at_ref
            or (self.expires_at_ref is None) != (self.expires_at_epoch_ns is None)
            or not self.now_ref
            or not self.source_ref
            or not self.source_digest
        ):
            raise RALValidationError(
                "authority_time_mismatch", "authority time references differ"
            )
        if self.now_epoch_ns < self.valid_from_epoch_ns or (
            self.expires_at_epoch_ns is not None
            and self.now_epoch_ns > self.expires_at_epoch_ns
        ):
            raise RALValidationError(
                "authority_time_inactive", "authority is outside its time window"
            )


@dataclass(frozen=True)
class RawPrincipalItemSnapshot:
    provider: str
    adapter_kind: str
    native_thread_id: str
    native_turn_id: str
    source_item_role: str
    source_item_kind: str
    source_item_status: str
    source_item_parent_thread_id: str
    source_item_parent_turn_id: str
    source_item_ref: str
    content_bytes: bytes = field(repr=False)

    def evidence_material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.raw-principal-item-snapshot/0.1",
            "provider": self.provider,
            "adapter_kind": self.adapter_kind,
            "native_thread_id": self.native_thread_id,
            "native_turn_id": self.native_turn_id,
            "source_item_role": self.source_item_role,
            "source_item_kind": self.source_item_kind,
            "source_item_status": self.source_item_status,
            "source_item_parent_thread_id": self.source_item_parent_thread_id,
            "source_item_parent_turn_id": self.source_item_parent_turn_id,
            "source_item_ref": self.source_item_ref,
            "content_sha256": hashlib.sha256(self.content_bytes).hexdigest(),
        }

    @property
    def evidence_digest(self) -> str:
        return sha256_ref(self.evidence_material())


@dataclass(frozen=True)
class PrincipalHostObservation:
    provider: str
    adapter_kind: str
    native_thread_id: str
    native_turn_id: str
    source_item_role: str
    source_item_kind: str
    source_item_status: str
    source_item_ref: str
    observed_origin: str
    observed_at_ref: str
    observation_ref: str
    digest: str

    @classmethod
    def sealed(
        cls,
        *,
        provider: str,
        adapter_kind: str,
        native_thread_id: str,
        native_turn_id: str,
        source_item_role: str,
        source_item_kind: str,
        source_item_status: str,
        source_item_ref: str,
        observed_origin: str,
        observed_at_ref: str,
    ) -> PrincipalHostObservation:
        observation_ref = f"principal-host-observation:{native_turn_id}"
        material = {
            "schema": "sedb-ral.principal-host-observation/0.1",
            "provider": provider,
            "adapter_kind": adapter_kind,
            "native_thread_id": native_thread_id,
            "native_turn_id": native_turn_id,
            "source_item_role": source_item_role,
            "source_item_kind": source_item_kind,
            "source_item_status": source_item_status,
            "source_item_ref": source_item_ref,
            "observed_origin": observed_origin,
            "observed_at_ref": observed_at_ref,
            "observation_ref": observation_ref,
        }
        return cls(
            provider=provider,
            adapter_kind=adapter_kind,
            native_thread_id=native_thread_id,
            native_turn_id=native_turn_id,
            source_item_role=source_item_role,
            source_item_kind=source_item_kind,
            source_item_status=source_item_status,
            source_item_ref=source_item_ref,
            observed_origin=observed_origin,
            observed_at_ref=observed_at_ref,
            observation_ref=observation_ref,
            digest=sha256_ref(material),
        )

    def verify(self) -> None:
        material = {
            "schema": "sedb-ral.principal-host-observation/0.1",
            "provider": self.provider,
            "adapter_kind": self.adapter_kind,
            "native_thread_id": self.native_thread_id,
            "native_turn_id": self.native_turn_id,
            "source_item_role": self.source_item_role,
            "source_item_kind": self.source_item_kind,
            "source_item_status": self.source_item_status,
            "source_item_ref": self.source_item_ref,
            "observed_origin": self.observed_origin,
            "observed_at_ref": self.observed_at_ref,
            "observation_ref": self.observation_ref,
        }
        if sha256_ref(material) != self.digest:
            raise RALValidationError(
                "principal_host_observation_mismatch",
                "principal host observation digest differs",
            )


@dataclass(frozen=True)
class VerifiedApplicationApproval:
    approval: PrincipalApplicationApproval
    application: dict[str, object]
    raw_item: RawPrincipalItemSnapshot = field(repr=False)
    host: PrincipalHostObservation
    application_digest: str
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _APPROVAL_TOKEN:
            raise RALValidationError(
                "verified_application_approval_required",
                "application approval capability was not verifier-issued",
            )

    def verify(self) -> None:
        self.host.verify()
        if sha256_ref(self.application) != self.application_digest:
            raise RALValidationError(
                "verified_application_approval_required",
                "approved application bytes changed",
            )
        material = {
            "approval_digest": self.approval.digest,
            "application_digest": self.application_digest,
            "raw_item_digest": self.raw_item.evidence_digest,
            "host_observation_digest": self.host.digest,
        }
        if sha256_ref(material) != self.verification_digest:
            raise RALValidationError(
                "verified_application_approval_required",
                "approval capability digest differs",
            )


@dataclass(frozen=True)
class VerifiedSlotExecutionAuthorization:
    authorization: SlotExecutionAuthorization
    approval: VerifiedApplicationApproval
    request_digest: str
    plan_digest: str
    current_status_digest: str
    application_approval_digest: str
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _EXECUTION_TOKEN:
            raise RALValidationError(
                "verified_slot_execution_required",
                "slot execution capability was not verifier-issued",
            )

    def verify(self) -> None:
        self.approval.verify()
        material = {
            "authorization_digest": self.authorization.digest,
            "approval_capability_digest": self.approval.verification_digest,
            "request_digest": self.request_digest,
            "plan_digest": self.plan_digest,
            "current_status_digest": self.current_status_digest,
        }
        if (
            self.application_approval_digest != self.approval.approval.digest
            or sha256_ref(material) != self.verification_digest
        ):
            raise RALValidationError(
                "verified_slot_execution_required",
                "slot execution capability digest differs",
            )


def _parse_raw_intent(raw_item: RawPrincipalItemSnapshot) -> dict[str, object]:
    try:
        value = loads_strict(raw_item.content_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise RALValidationError(
            "principal_intent_invalid", "principal intent is not strict UTF-8 JSON"
        ) from error
    if not isinstance(value, dict) or canonical_bytes(value) != raw_item.content_bytes:
        raise RALValidationError(
            "principal_intent_invalid", "principal intent is not canonical"
        )
    return value


def _verify_user_item(
    raw_item: RawPrincipalItemSnapshot,
    host: PrincipalHostObservation,
    expected_intent: Mapping[str, object],
) -> None:
    host.verify()
    if (
        raw_item.source_item_role,
        raw_item.source_item_kind,
        raw_item.source_item_status,
        host.source_item_role,
        host.source_item_kind,
        host.source_item_status,
    ) != ("user", "userMessage", "completed", "user", "userMessage", "completed"):
        raise RALValidationError(
            "principal_authorship_unverified",
            "principal evidence is not a completed host-observed user message",
        )
    if (
        raw_item.provider != host.provider
        or raw_item.adapter_kind != host.adapter_kind
        or raw_item.native_thread_id != host.native_thread_id
        or raw_item.native_turn_id != host.native_turn_id
        or raw_item.source_item_parent_thread_id != host.native_thread_id
        or raw_item.source_item_parent_turn_id != host.native_turn_id
        or raw_item.source_item_ref != host.source_item_ref
        or not host.observed_origin.startswith("host:")
        or _parse_raw_intent(raw_item) != _canonical_object(expected_intent)
    ):
        raise RALValidationError(
            "principal_authorship_unverified",
            "principal item, host observation, or intent differs",
        )


def verify_application_approval(
    approval: Mapping[str, object] | PrincipalApplicationApproval,
    application: Mapping[str, object],
    principal_item: RawPrincipalItemSnapshot,
    host_observation: PrincipalHostObservation,
    *,
    expected_principal_ref: str,
    time: AuthorityTimeEvidence,
) -> VerifiedApplicationApproval:
    parsed = (
        approval
        if isinstance(approval, PrincipalApplicationApproval)
        else PrincipalApplicationApproval.from_dict(approval)
    )
    canonical_application = _canonical_object(application)
    application_digest = sha256_ref(canonical_application)
    expected_intent = {
        "schema": "sedb-ral.principal-application-approval-intent/0.1",
        "principal_ref": expected_principal_ref,
        "application_ref": canonical_application["application_id"],
        "application_digest": application_digest,
        "approved_scopes": ["registration.application.approve"],
    }
    _verify_user_item(principal_item, host_observation, expected_intent)
    if (
        parsed.principal_ref != expected_principal_ref
        or parsed.application_ref != canonical_application["application_id"]
        or parsed.application_digest != application_digest
        or parsed.source_user_item_ref != principal_item.source_item_ref
        or parsed.source_user_item_digest != principal_item.evidence_digest
        or parsed.host_observation_ref != host_observation.observation_ref
        or parsed.host_observation_digest != host_observation.digest
        or parsed.status != "active"
    ):
        raise RALValidationError(
            "principal_approval_mismatch",
            "application approval binds another principal or application",
        )
    time.verify(parsed.valid_from_ref, parsed.expires_at_ref)
    material = {
        "approval_digest": parsed.digest,
        "application_digest": application_digest,
        "raw_item_digest": principal_item.evidence_digest,
        "host_observation_digest": host_observation.digest,
    }
    return VerifiedApplicationApproval(
        approval=parsed,
        application=canonical_application,
        raw_item=principal_item,
        host=host_observation,
        application_digest=application_digest,
        verification_digest=sha256_ref(material),
        _token=_APPROVAL_TOKEN,
    )


def verify_slot_execution_authorization(
    authorization: Mapping[str, object] | SlotExecutionAuthorization | None,
    plan: Mapping[str, object] | RegistrationWavePlan,
    slot_request: Mapping[str, object] | WaveSlotRequest,
    approval: VerifiedApplicationApproval,
    policy: Mapping[str, object] | RegistrationWavePolicy,
    checkpoint: Mapping[str, object],
    current_status: Mapping[str, object],
    principal_item: RawPrincipalItemSnapshot | None,
    host_observation: PrincipalHostObservation | None,
    *,
    expected_principal_ref: str,
    time: AuthorityTimeEvidence,
) -> VerifiedSlotExecutionAuthorization:
    if authorization is None:
        raise RALValidationError(
            "slot_execution_authorization_missing",
            "application approval does not authorize execution",
        )
    if not isinstance(approval, VerifiedApplicationApproval):
        raise RALValidationError(
            "verified_application_approval_required",
            "slot execution requires verified application approval",
        )
    if principal_item is None or host_observation is None:
        raise RALValidationError(
            "principal_authorship_unverified",
            "execution authorization lacks principal evidence",
        )
    approval.verify()
    parsed = (
        authorization
        if isinstance(authorization, SlotExecutionAuthorization)
        else SlotExecutionAuthorization.from_dict(authorization)
    )
    parsed_plan = (
        plan if isinstance(plan, RegistrationWavePlan) else RegistrationWavePlan.from_dict(plan)
    )
    request = (
        slot_request
        if isinstance(slot_request, WaveSlotRequest)
        else WaveSlotRequest.from_dict(slot_request)
    )
    parsed_policy = (
        policy
        if isinstance(policy, RegistrationWavePolicy)
        else RegistrationWavePolicy.from_dict(policy)
    )
    checkpoint_value = _canonical_object(checkpoint)
    status = _canonical_object(current_status)
    expected_status_fields = {
        "wave_status",
        "policy_ref",
        "policy_digest",
        "checkpoint_ref",
        "checkpoint_digest",
        "registry_generation_digest",
        "registry_control_digest",
        "current_ledger_head",
    }
    if set(status) != expected_status_fields or status["wave_status"] != "active":
        raise RALValidationError(
            "slot_execution_binding_mismatch", "current Wave status is not active"
        )
    expected_intent = {
        "schema": "sedb-ral.registration-slot-execution-intent/0.1",
        "principal_ref": expected_principal_ref,
        "wave_plan_ref": f"registration-wave-plan:{parsed_plan.wave_id}",
        "wave_plan_digest": parsed_plan.digest,
        "slot_id": request.slot_id,
        "slot_index": request.slot_index,
        "operation_request_ref": request.request_id,
        "operation_request_digest": request.digest,
        "application_approval_ref": approval.approval.approval_id,
        "application_approval_digest": approval.approval.digest,
        "policy_ref": parsed_plan.policy_ref,
        "policy_digest": parsed_plan.policy_digest,
        "checkpoint_ref": parsed_plan.checkpoint_ref,
        "checkpoint_digest": parsed_plan.checkpoint_digest,
        "expected_ledger_head": request.expected_ledger_state[
            "expected_ledger_head"
        ],
        "registry_control_digest": parsed_plan.registry_control_digest,
    }
    _verify_user_item(principal_item, host_observation, expected_intent)
    if (
        parsed.principal_ref != expected_principal_ref
        or parsed.wave_plan_ref != expected_intent["wave_plan_ref"]
        or parsed.wave_plan_digest != parsed_plan.digest
        or parsed.slot_id != request.slot_id
        or parsed.slot_index != request.slot_index
        or parsed.operation_request_ref != request.request_id
        or parsed.operation_request_digest != request.digest
        or parsed.application_approval_ref != approval.approval.approval_id
        or parsed.application_approval_digest != approval.approval.digest
        or parsed.policy_ref != parsed_plan.policy_ref
        or parsed.policy_digest != parsed_plan.policy_digest
        or parsed.checkpoint_ref != parsed_plan.checkpoint_ref
        or parsed.checkpoint_digest != parsed_plan.checkpoint_digest
        or parsed.expected_ledger_head
        != request.expected_ledger_state["expected_ledger_head"]
        or parsed.registry_control_digest != parsed_plan.registry_control_digest
        or parsed.source_user_item_ref != principal_item.source_item_ref
        or parsed.source_user_item_digest != principal_item.evidence_digest
        or parsed.host_observation_ref != host_observation.observation_ref
        or parsed.host_observation_digest != host_observation.digest
        or parsed.status != "active"
        or parsed_policy.digest != parsed_plan.policy_digest
        or parsed_policy.policy_id != parsed_plan.policy_ref
        or checkpoint_value.get("checkpoint_ref") != parsed_plan.checkpoint_ref
        or checkpoint_value.get("checkpoint_digest") != parsed_plan.checkpoint_digest
        or status["policy_ref"] != parsed_plan.policy_ref
        or status["policy_digest"] != parsed_plan.policy_digest
        or status["checkpoint_ref"] != parsed_plan.checkpoint_ref
        or status["checkpoint_digest"] != parsed_plan.checkpoint_digest
        or status["registry_generation_digest"]
        != parsed_plan.registry_generation_digest
        or status["registry_control_digest"] != parsed_plan.registry_control_digest
        or status["current_ledger_head"]
        != request.expected_ledger_state["expected_ledger_head"]
    ):
        raise RALValidationError(
            "slot_execution_binding_mismatch",
            "execution authorization binds stale or different state",
        )
    time.verify(parsed.valid_from_ref, parsed.expires_at_ref)
    status_digest = sha256_ref(status)
    material = {
        "authorization_digest": parsed.digest,
        "approval_capability_digest": approval.verification_digest,
        "request_digest": request.digest,
        "plan_digest": parsed_plan.digest,
        "current_status_digest": status_digest,
    }
    return VerifiedSlotExecutionAuthorization(
        authorization=parsed,
        approval=approval,
        request_digest=request.digest,
        plan_digest=parsed_plan.digest,
        current_status_digest=status_digest,
        application_approval_digest=approval.approval.digest,
        verification_digest=sha256_ref(material),
        _token=_EXECUTION_TOKEN,
    )
