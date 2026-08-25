from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from ..canonical import canonical_bytes, loads_strict, sha256_ref
from ..contracts import validate_contract
from ..errors import RALValidationError

OPERATION_KINDS = (
    "inspect",
    "prepare",
    "plan",
    "execute",
    "reject",
    "withdraw",
    "suspend_address",
    "revoke_authority",
    "status",
    "export_public",
)
FORBIDDEN_INTAKE_FIELDS = frozenset(
    {
        "canonical_root",
        "expected_head",
        "operator_ref",
        "policy_digest",
        "authority",
        "checkpoint_ref",
        "private_path",
    }
)
FORBIDDEN_CAPABILITIES = (
    "production_mutation",
    "real_applicant",
    "private_access",
    "network_send",
    "fabric_emit",
)


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("operations contract must remain an object")
    return canonical


def _verify_digest(value: Mapping[str, object], field: str, error_code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(error_code, "bound operations digest differs")


@dataclass(frozen=True)
class _CanonicalContract:
    _canonical: bytes

    schema_name: ClassVar[str]
    digest_field: ClassVar[str]
    digest_error: ClassVar[str]

    @property
    def digest(self) -> str:
        return str(self.to_dict()[self.digest_field])

    def to_dict(self) -> dict[str, object]:
        value = loads_strict(self._canonical.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("stored operations contract must remain an object")
        return value

    @classmethod
    def _parse(cls, value: Mapping[str, object]) -> _CanonicalContract:
        canonical = _canonical_object(value)
        _verify_digest(canonical, cls.digest_field, cls.digest_error)
        validate_contract(cls.schema_name, canonical)
        return cls(canonical_bytes(canonical))


@dataclass(frozen=True)
class ForeignSchemaPin(_CanonicalContract):
    schema_name = "foreign-schema-pin.schema.json"
    digest_field = "pin_digest"
    digest_error = "foreign_schema_pin_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ForeignSchemaPin:
        canonical = _canonical_object(value)
        validate_contract(cls.schema_name, canonical)
        _verify_digest(canonical, cls.digest_field, cls.digest_error)
        return cls(canonical_bytes(canonical))


@dataclass(frozen=True)
class OperationsPolicy(_CanonicalContract):
    schema_name = "registrar-operations-policy.schema.json"
    digest_field = "policy_digest"
    digest_error = "operations_policy_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OperationsPolicy:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        capabilities = canonical["capabilities"]
        if any(capabilities[name] is not False for name in FORBIDDEN_CAPABILITIES):
            raise RALValidationError(
                "operations_policy_forbidden_capability",
                "R3B-A policy enables a forbidden capability",
            )
        if tuple(canonical["allowed_operation_kinds"]) != OPERATION_KINDS:
            raise RALValidationError(
                "operations_policy_operation_inventory_mismatch",
                "operation inventory differs from J0",
            )
        return cls(parsed._canonical)


@dataclass(frozen=True)
class RegistrarIntake(_CanonicalContract):
    schema_name = "registrar-intake.schema.json"
    digest_field = "intake_digest"
    digest_error = "registrar_intake_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistrarIntake:
        if FORBIDDEN_INTAKE_FIELDS & set(value):
            raise RALValidationError(
                "registrar_intake_forbidden_field",
                "applicant intake contains operational evidence",
            )
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        if (canonical["prepared_ref"] is None) != (
            canonical["prepared_digest"] is None
        ):
            raise RALValidationError(
                "registrar_intake_prepared_pair_invalid",
                "prepared ref and digest must both be present or absent",
            )
        if (canonical["durable_handoff_ref"] is None) != (
            canonical["durable_handoff_digest"] is None
        ):
            raise RALValidationError(
                "registrar_intake_handoff_pair_invalid",
                "handoff ref and digest must both be present or absent",
            )
        return cls(parsed._canonical)


@dataclass(frozen=True)
class OperatorObservation(_CanonicalContract):
    schema_name = "registrar-operator-observation.schema.json"
    digest_field = "observation_digest"
    digest_error = "operator_observation_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OperatorObservation:
        parsed = cls._parse(value)
        return cls(parsed._canonical)


@dataclass(frozen=True)
class OperationRequest(_CanonicalContract):
    schema_name = "registrar-operation-request.schema.json"
    digest_field = "operation_digest"
    digest_error = "operation_request_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OperationRequest:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        for pin in canonical["foreign_evidence_pins"]:
            ForeignSchemaPin.from_dict(pin)
        for ref_field, digest_field in (
            ("authority_artifact_ref", "authority_artifact_digest"),
            ("checkpoint_evidence_ref", "checkpoint_evidence_digest"),
        ):
            if (canonical[ref_field] is None) != (canonical[digest_field] is None):
                raise RALValidationError(
                    "operation_request_reference_pair_invalid",
                    f"{ref_field} and {digest_field} must be paired",
                )
        return cls(parsed._canonical)


@dataclass(frozen=True)
class OperationReceipt(_CanonicalContract):
    schema_name = "registrar-operation-receipt.schema.json"
    digest_field = "receipt_digest"
    digest_error = "operation_receipt_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OperationReceipt:
        parsed = cls._parse(value)
        return cls(parsed._canonical)


@dataclass(frozen=True)
class OperationsManifest(_CanonicalContract):
    schema_name = "registrar-operations-manifest.schema.json"
    digest_field = "manifest_digest"
    digest_error = "operations_manifest_digest_mismatch"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OperationsManifest:
        parsed = cls._parse(value)
        canonical = parsed.to_dict()
        for pin in canonical["fabric_schema_pins"]:
            ForeignSchemaPin.from_dict(pin)
        return cls(parsed._canonical)
