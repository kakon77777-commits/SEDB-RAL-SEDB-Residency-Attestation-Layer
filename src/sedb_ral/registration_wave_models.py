from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Self

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError

_CANONICAL_THREAD = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SLOT_FIELDS = frozenset(
    {
        "slot_id",
        "slot_index",
        "candidate_ref",
        "candidate_digest",
        "application_ref",
        "application_digest",
        "host_observation_ref",
        "host_observation_digest",
    }
)


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("registration wave contract must remain an object")
    return canonical


def _verify_digest(value: Mapping[str, object], field: str, code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(code, "registration wave digest differs")


def _require_pair(
    value: Mapping[str, object], ref_field: str, digest_field: str, code: str
) -> None:
    if (value[ref_field] is None) != (value[digest_field] is None):
        raise RALValidationError(code, f"{ref_field} and {digest_field} must pair")


def _require_canonical_thread(value: object, code: str) -> None:
    if not isinstance(value, str) or _CANONICAL_THREAD.fullmatch(value) is None:
        raise RALValidationError(code, "codex_thread locator is not canonical")


def verify_ref_digest_registry(
    records: Sequence[Mapping[str, object]],
    pairs: Sequence[tuple[str, str, str]],
    *,
    code: str,
) -> None:
    seen_refs: dict[str, tuple[str, str]] = {}
    seen_digests: dict[str, tuple[str, str]] = {}
    for record in records:
        for kind, ref_field, digest_field in pairs:
            ref = record[ref_field]
            digest = record[digest_field]
            if not isinstance(ref, str) or not ref or not isinstance(digest, str) or not digest:
                raise RALValidationError(code, f"{kind} identity pair is invalid")
            if ref in seen_refs or digest in seen_digests:
                raise RALValidationError(
                    code,
                    f"{kind} ref/digest is reused across the identity registry",
                )
            seen_refs[ref] = (kind, digest)
            seen_digests[digest] = (kind, ref)


@dataclass(frozen=True)
class _WaveContract:
    _canonical: bytes

    schema_name: ClassVar[str]
    digest_field: ClassVar[str]
    digest_error: ClassVar[str]

    @property
    def digest(self) -> str:
        return str(self.to_dict()[self.digest_field])

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        value = self.to_dict()
        if name not in value:
            raise AttributeError(name)
        return value[name]

    def to_dict(self) -> dict[str, object]:
        value = loads_strict(self._canonical.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("stored registration wave contract must be an object")
        return value

    @classmethod
    def _parse(cls, value: Mapping[str, object]) -> Self:
        canonical = _canonical_object(value)
        _verify_digest(canonical, cls.digest_field, cls.digest_error)
        validate_contract(cls.schema_name, canonical)
        return cls(canonical_bytes(canonical))

    @classmethod
    def sealed(cls, material: Mapping[str, object]) -> Self:
        value = _canonical_object(material)
        value.pop(cls.digest_field, None)
        value[cls.digest_field] = sha256_ref(value)
        return cls.from_dict(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        return cls._parse(value)

    def verify(self) -> None:
        type(self).from_dict(self.to_dict())


@dataclass(frozen=True)
class WaveSlot:
    slot_id: str
    slot_index: int
    candidate_ref: str
    candidate_digest: str
    application_ref: str
    application_digest: str
    host_observation_ref: str
    host_observation_digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> WaveSlot:
        if set(value) != _SLOT_FIELDS:
            raise RALValidationError(
                "wave_slot_fields_invalid", "wave slot fields differ"
            )
        if value["slot_index"] not in (1, 2, 3):
            raise RALValidationError(
                "wave_slot_index_invalid", "slot index must be 1, 2, or 3"
            )
        for name in _SLOT_FIELDS - {"slot_index"}:
            if not isinstance(value[name], str) or not value[name]:
                raise RALValidationError(
                    "wave_slot_field_invalid", f"{name} must be non-empty"
                )
        return cls(**dict(value))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "slot_index": self.slot_index,
            "candidate_ref": self.candidate_ref,
            "candidate_digest": self.candidate_digest,
            "application_ref": self.application_ref,
            "application_digest": self.application_digest,
            "host_observation_ref": self.host_observation_ref,
            "host_observation_digest": self.host_observation_digest,
        }

    def verify(self) -> None:
        type(self).from_dict(self.to_dict())

class ApplicantItemEvidence(_WaveContract):
    schema_name = "registration-applicant-item-evidence.schema.json"
    digest_field = "item_evidence_digest"
    digest_error = "applicant_item_evidence_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ApplicantItemEvidence:
        canonical = _canonical_object(value)
        if (
            canonical.get("source_item_role"),
            canonical.get("source_item_kind"),
            canonical.get("source_item_status"),
        ) != ("assistant", "agentMessage", "completed"):
            raise RALValidationError(
                "applicant_item_role_invalid",
                "applicant item is not completed assistant output",
            )
        if (
            canonical.get("native_thread_id")
            != canonical.get("source_item_parent_thread_id")
            or canonical.get("native_turn_id")
            != canonical.get("source_item_parent_turn_id")
        ):
            raise RALValidationError(
                "applicant_item_parent_mismatch", "applicant item parent differs"
            )
        _require_canonical_thread(
            canonical.get("native_thread_id"), "applicant_thread_locator_invalid"
        )
        return cls._parse(canonical)


class WaveHostObservation(_WaveContract):
    schema_name = "registration-host-observation-v0.2.schema.json"
    digest_field = "observation_digest"
    digest_error = "host_observation_digest_mismatch"


class RegistrationWavePreparedCandidate(_WaveContract):
    schema_name = "registration-wave-prepared-candidate.schema.json"
    digest_field = "candidate_digest"
    digest_error = "wave_candidate_digest_mismatch"

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> RegistrationWavePreparedCandidate:
        parsed = cls._parse(value)
        _require_canonical_thread(
            parsed.to_dict()["canonical_locator"], "wave_candidate_locator_invalid"
        )
        return parsed


class RegistrationWavePlan(_WaveContract):
    schema_name = "registration-wave-plan.schema.json"
    digest_field = "wave_plan_digest"
    digest_error = "wave_plan_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistrationWavePlan:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        slots = tuple(WaveSlot.from_dict(item) for item in canonical["ordered_slots"])
        if tuple(slot.slot_index for slot in slots) != (1, 2, 3):
            raise RALValidationError(
                "wave_slot_order_invalid", "wave slots are not contiguous"
            )
        for name in (
            "slot_id",
        ):
            values = [getattr(slot, name) for slot in slots]
            if len(set(values)) != 3:
                raise RALValidationError(
                    "wave_slot_binding_duplicate", f"{name} must be distinct"
                )
        verify_ref_digest_registry(
            tuple(slot.to_dict() for slot in slots),
            (
                ("candidate", "candidate_ref", "candidate_digest"),
                ("application", "application_ref", "application_digest"),
                (
                    "host_observation",
                    "host_observation_ref",
                    "host_observation_digest",
                ),
            ),
            code="wave_slot_binding_duplicate",
        )
        return parsed


class RegistrationWavePolicy(_WaveContract):
    schema_name = "registration-wave-policy.schema.json"
    digest_field = "policy_digest"
    digest_error = "wave_policy_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistrationWavePolicy:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        locators = canonical["ordered_locators"]
        for locator in locators:
            _require_canonical_thread(locator, "wave_policy_locator_invalid")
        if len(set(locators)) != 3:
            raise RALValidationError(
                "wave_policy_locator_duplicate", "policy locators must be distinct"
            )
        if len(set(canonical["ordered_application_digests"])) != 3:
            raise RALValidationError(
                "wave_policy_application_duplicate",
                "policy applications must be distinct",
            )
        return parsed


class ActiveWavePolicyRecord(_WaveContract):
    schema_name = "registration-wave-active-policy-record.schema.json"
    digest_field = "record_digest"
    digest_error = "active_wave_policy_record_digest_mismatch"


class WavePolicyActivationRequest(_WaveContract):
    schema_name = "registration-wave-policy-activation-request.schema.json"
    digest_field = "request_digest"
    digest_error = "wave_policy_activation_request_digest_mismatch"

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> WavePolicyActivationRequest:
        parsed = cls._parse(value)
        approvals = parsed.to_dict()["application_approval_digests"]
        if len(approvals) != 3 or len(set(approvals)) != 3:
            raise RALValidationError(
                "wave_exact_three_approvals_required",
                "activation requires three distinct approvals",
            )
        return parsed


class WavePolicyActivationAuthority(_WaveContract):
    schema_name = "registration-wave-policy-activation-authority.schema.json"
    digest_field = "authority_digest"
    digest_error = "wave_policy_activation_authority_digest_mismatch"


class WavePolicyActivationReceipt(_WaveContract):
    schema_name = "registration-wave-policy-activation-receipt.schema.json"
    digest_field = "receipt_digest"
    digest_error = "wave_policy_activation_receipt_digest_mismatch"


class PrincipalApplicationApproval(_WaveContract):
    schema_name = "principal-application-approval.schema.json"
    digest_field = "approval_digest"
    digest_error = "principal_application_approval_digest_mismatch"


class SlotExecutionAuthorization(_WaveContract):
    schema_name = "registration-slot-execution-authorization.schema.json"
    digest_field = "execution_authorization_digest"
    digest_error = "slot_execution_authorization_digest_mismatch"


class WaveSlotRequest(_WaveContract):
    schema_name = "registration-wave-slot-request.schema.json"
    digest_field = "request_digest"
    digest_error = "wave_slot_request_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> WaveSlotRequest:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        _require_pair(
            canonical,
            "predecessor_receipt_ref",
            "predecessor_receipt_digest",
            "wave_predecessor_pair_invalid",
        )
        index = canonical["slot_index"]
        predecessor = canonical["predecessor_receipt_ref"]
        if (index == 1) != (predecessor is None):
            raise RALValidationError(
                "wave_predecessor_invalid",
                "only slot 1 may omit predecessor receipt",
            )
        return parsed


class SyntheticWaveSlotExecutionResult(_WaveContract):
    schema_name = "synthetic-wave-slot-execution-result.schema.json"
    digest_field = "result_digest"
    digest_error = "synthetic_wave_slot_result_digest_mismatch"


class WaveSlotReceipt(_WaveContract):
    schema_name = "registration-wave-slot-receipt.schema.json"
    digest_field = "receipt_digest"
    digest_error = "wave_slot_receipt_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> WaveSlotReceipt:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        _require_pair(
            canonical,
            "limen_b6a_result_ref",
            "limen_b6a_result_digest",
            "wave_slot_limen_pair_invalid",
        )
        return parsed


class WaveSlotRecoveryAuthorization(_WaveContract):
    schema_name = "registration-wave-slot-recovery-authorization.schema.json"
    digest_field = "recovery_authorization_digest"
    digest_error = "wave_slot_recovery_authorization_digest_mismatch"


class SyntheticWaveSlotRecoveryResult(_WaveContract):
    schema_name = "synthetic-wave-slot-recovery-result.schema.json"
    digest_field = "result_digest"
    digest_error = "synthetic_wave_recovery_result_digest_mismatch"


class WaveSlotRecoveryReceipt(_WaveContract):
    schema_name = "registration-wave-slot-recovery-receipt.schema.json"
    digest_field = "receipt_digest"
    digest_error = "wave_slot_recovery_receipt_digest_mismatch"


class WaveTerminalEvent(_WaveContract):
    schema_name = "registration-wave-terminal-event.schema.json"
    digest_field = "event_digest"
    digest_error = "wave_terminal_event_digest_mismatch"


class WaveReadbackBundle(_WaveContract):
    schema_name = "registration-wave-readback-bundle.schema.json"
    digest_field = "bundle_digest"
    digest_error = "wave_readback_bundle_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> WaveReadbackBundle:
        parsed = cls._parse(value)
        indexes = parsed.to_dict()["admitted_slot_indexes"]
        if indexes != sorted(set(indexes)):
            raise RALValidationError(
                "wave_readback_slot_indexes_invalid",
                "readback slot indexes must be sorted and unique",
            )
        return parsed
