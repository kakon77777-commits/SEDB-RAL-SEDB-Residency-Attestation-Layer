from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from uuid import UUID

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .registry_root_contracts import bind_document_digest


PRODUCTION_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
EXTENSION_REF = "extensions/registrar-operations/v1"
ACTIVATION_OPERATION = "registry.operations-extension.activate"
ACTIVATION_SCOPES = (ACTIVATION_OPERATION,)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("production operations contract must remain an object")
    return canonical


def _verify_digest(
    value: Mapping[str, object], field: str, code: str
) -> dict[str, object]:
    canonical = _canonical_object(value)
    material = dict(canonical)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(code, "production operations digest differs")
    return canonical


def _validate_uuid4(value: str) -> None:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise RALValidationError(
            "production_operations_candidate_id_invalid",
            "candidate ID must be canonical UUID4",
        ) from error
    if parsed.version != 4 or str(parsed) != value:
        raise RALValidationError(
            "production_operations_candidate_id_invalid",
            "candidate ID must be canonical UUID4",
        )


@dataclass(frozen=True)
class _CanonicalContract:
    _canonical: bytes
    digest_field: str

    @property
    def digest(self) -> str:
        return str(self.to_dict()[self.digest_field])

    def to_dict(self) -> dict[str, object]:
        value = loads_strict(self._canonical.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("stored production operations contract must be an object")
        return value


def _parse(
    cls,
    value: Mapping[str, object],
    *,
    schema_name: str,
    digest_field: str,
    digest_code: str,
):
    canonical = _verify_digest(value, digest_field, digest_code)
    validate_contract(schema_name, canonical)
    return cls(canonical_bytes(canonical), digest_field)


@dataclass(frozen=True)
class ProductionOperationsPlan(_CanonicalContract):
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ProductionOperationsPlan":
        parsed = _parse(
            cls,
            value,
            schema_name="production-operations-extension-plan.schema.json",
            digest_field="plan_digest",
            digest_code="production_operations_plan_digest_mismatch",
        )
        canonical = parsed.to_dict()
        _validate_uuid4(str(canonical["candidate_id"]))
        if canonical["final_root"] != PRODUCTION_ROOT:
            raise RALValidationError(
                "production_operations_target_mismatch",
                "production operations target differs",
            )
        return parsed


@dataclass(frozen=True)
class ProductionOperationsAuthority(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ProductionOperationsAuthority":
        return _parse(
            cls,
            value,
            schema_name="production-operations-extension-authority.schema.json",
            digest_field="authority_digest",
            digest_code="production_operations_authority_digest_mismatch",
        )


@dataclass(frozen=True)
class ProductionOperationsManifest(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ProductionOperationsManifest":
        return _parse(
            cls,
            value,
            schema_name="production-operations-extension-manifest.schema.json",
            digest_field="manifest_digest",
            digest_code="production_operations_manifest_digest_mismatch",
        )


@dataclass(frozen=True)
class ProductionOperationsPolicy(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ProductionOperationsPolicy":
        return _parse(
            cls,
            value,
            schema_name="production-operations-policy.schema.json",
            digest_field="policy_digest",
            digest_code="production_operations_policy_digest_mismatch",
        )


@dataclass(frozen=True)
class ProductionOperationsActivationCommit(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ProductionOperationsActivationCommit":
        return _parse(
            cls,
            value,
            schema_name="production-operations-activation-commit.schema.json",
            digest_field="commit_digest",
            digest_code="production_operations_commit_digest_mismatch",
        )


@dataclass(frozen=True)
class ProductionOperationsActivationReceipt(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ProductionOperationsActivationReceipt":
        return _parse(
            cls,
            value,
            schema_name="production-operations-activation-receipt.schema.json",
            digest_field="receipt_digest",
            digest_code="production_operations_receipt_digest_mismatch",
        )


@dataclass(frozen=True)
class RegistryExtensionIndex(_CanonicalContract):
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RegistryExtensionIndex":
        return _parse(
            cls,
            value,
            schema_name="registry-extension-index.schema.json",
            digest_field="index_digest",
            digest_code="registry_extension_index_digest_mismatch",
        )


@dataclass(frozen=True)
class ProductionOperationsAcceptance(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ProductionOperationsAcceptance":
        return _parse(
            cls,
            value,
            schema_name="production-operations-acceptance.schema.json",
            digest_field="report_digest",
            digest_code="production_operations_acceptance_digest_mismatch",
        )


def plan_production_operations_extension(
    *,
    registry_status: Mapping[str, object],
    candidate_id: str,
    operations_generation: str,
    policy_digest: str,
    source_commit: str,
    source_package_version: str,
    filesystem: str,
    volume_identity: str,
    expected_owner_sid: str,
    acl_fingerprint: str,
    pre_checkpoint_digest: str,
    time_ref: str,
) -> dict[str, object]:
    required_counts = {
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
    }
    if registry_status.get("verified") is not True or any(
        registry_status.get(name) != expected
        for name, expected in required_counts.items()
    ):
        raise RALValidationError(
            "production_operations_registry_not_empty",
            "production operations activation requires an empty verified registry",
        )
    _validate_uuid4(candidate_id)
    if operations_generation != f"operations-generation:{candidate_id}":
        raise RALValidationError(
            "production_operations_generation_mismatch",
            "operations generation does not bind candidate ID",
        )
    if not _HEX40.fullmatch(source_commit):
        raise RALValidationError(
            "production_operations_source_commit_invalid",
            "source commit must be a lowercase SHA-1",
        )
    if filesystem.upper() != "NTFS":
        raise RALValidationError(
            "production_operations_filesystem_mismatch", "NTFS is required"
        )
    material: dict[str, object] = {
        "schema": "sedb-ral.production-operations-extension-plan/0.1",
        "final_root": PRODUCTION_ROOT,
        "extension_ref": EXTENSION_REF,
        "candidate_id": candidate_id,
        "candidate_name": f".SEDB-RAL.operations-{candidate_id}",
        "operations_generation": operations_generation,
        "registry_id": registry_status["registry_id"],
        "registry_manifest_digest": registry_status["manifest_digest"],
        "registry_control_digest": registry_status["control_digest"],
        "base_tree_digest": registry_status["tree_digest"],
        "required_counts": required_counts,
        "policy_digest": policy_digest,
        "source_commit": source_commit,
        "source_package_version": source_package_version,
        "filesystem": "NTFS",
        "volume_identity": volume_identity,
        "expected_owner_sid": expected_owner_sid,
        "acl_fingerprint": acl_fingerprint,
        "pre_checkpoint_digest": pre_checkpoint_digest,
        "time_ref": time_ref,
        "not_claimed": [
            "resident_registration",
            "ledger_append",
            "private_access",
            "network_send",
            "provider_call",
            "fabric_emit",
            "mcp_call",
        ],
    }
    return ProductionOperationsPlan.from_dict(
        bind_document_digest(material, "plan_digest")
    ).to_dict()


def verify_production_operations_authority(
    authority: Mapping[str, object], *, plan_digest: str, exact_root: str
) -> dict[str, object]:
    parsed = ProductionOperationsAuthority.from_dict(authority).to_dict()
    if parsed["status"] != "active":
        raise RALValidationError(
            "production_operations_authority_inactive",
            "production operations authority is inactive",
        )
    if tuple(parsed["scopes"]) != ACTIVATION_SCOPES:
        raise RALValidationError(
            "production_operations_authority_scope_invalid",
            "production operations authority scopes differ",
        )
    if (
        parsed["operation"] != ACTIVATION_OPERATION
        or parsed["operation_plan_digest"] != plan_digest
        or parsed["target_root"] != exact_root
    ):
        raise RALValidationError(
            "production_operations_authority_mismatch",
            "production operations authority binds another action",
        )
    return parsed
