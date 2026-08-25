from __future__ import annotations

import ntpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError

PRODUCTION_REGISTRY_PARENT = r"D:\AI_RESIDENCE\REGISTRY"
PRODUCTION_REGISTRY_ROOT = PRODUCTION_REGISTRY_PARENT + r"\SEDB-RAL"
APPROVED_ROOT_SCOPES = (
    "registry.root.initialize",
    "registry.root.inspect_acl",
    "registry.root.checkpoint",
    "registry.root.rehearse_restore",
    "registry.root.rehearse_rollback",
)
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
FORBIDDEN_BROAD_SIDS = frozenset(
    {"S-1-5-11", "S-1-5-32-545", "S-1-1-0"}
)

_PLAN_NOT_CLAIMED = (
    "resident_registration",
    "private_access",
    "root_replacement",
    "root_deletion",
    "offsite_backup",
)
_HEX_COMMIT = re.compile(r"[0-9a-f]{40}")


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("canonical registry contract must remain an object")
    return canonical


def bind_document_digest(
    value: Mapping[str, object], digest_field: str
) -> dict[str, object]:
    if digest_field in value:
        raise RALValidationError(
            "digest_field_present",
            "digest material must exclude its digest field",
        )
    material = _canonical_object(value)
    return _canonical_object(
        {**material, digest_field: sha256_ref(material)}
    )


def _verify_document_digest(
    value: Mapping[str, object], digest_field: str, error_code: str
) -> None:
    material = dict(value)
    actual = material.pop(digest_field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(error_code, "bound document digest differs")


def _normalized_windows_path(value: object, error_code: str) -> str:
    if not isinstance(value, str) or not value:
        raise RALValidationError(error_code, "root path must be text")
    if value.startswith(("\\\\", "\\?\\", "\\.\\")):
        raise RALValidationError(error_code, "network and device paths are forbidden")
    normalized = ntpath.normpath(value)
    drive, tail = ntpath.splitdrive(normalized)
    if not drive or not tail.startswith("\\") or ".." in tail.split("\\"):
        raise RALValidationError(error_code, "root path must be absolute")
    return normalized


def _require_exact_root(value: object, expected: str, code: str) -> str:
    normalized = _normalized_windows_path(value, code)
    if normalized.casefold() != expected.casefold() or normalized != value:
        raise RALValidationError(code, "root path differs from the exact target")
    return normalized


@dataclass(frozen=True)
class _CanonicalContract:
    _canonical: bytes

    def to_dict(self) -> dict[str, object]:
        value = loads_strict(self._canonical.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("stored contract must remain an object")
        return value


@dataclass(frozen=True)
class RegistryRootPlan(_CanonicalContract):
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistryRootPlan:
        canonical = _canonical_object(value)
        _verify_document_digest(
            canonical, "plan_digest", "root_plan_digest_mismatch"
        )
        validate_contract("registry-root-plan.schema.json", canonical)
        _require_exact_root(
            canonical["final_root"], PRODUCTION_REGISTRY_ROOT, "root_target_mismatch"
        )
        _require_exact_root(
            canonical["registry_parent"],
            PRODUCTION_REGISTRY_PARENT,
            "root_parent_mismatch",
        )
        expected_candidate = ntpath.join(
            PRODUCTION_REGISTRY_PARENT, canonical["candidate_name"]
        )
        _require_exact_root(
            canonical["candidate_root"], expected_candidate, "candidate_target_mismatch"
        )
        if canonical["filesystem"].upper() != "NTFS":
            raise RALValidationError("filesystem_mismatch", "NTFS is required")
        return cls(canonical_bytes(canonical))


@dataclass(frozen=True)
class RegistryRootAuthority(_CanonicalContract):
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistryRootAuthority:
        canonical = _canonical_object(value)
        _verify_document_digest(
            canonical, "authority_digest", "root_authority_digest_mismatch"
        )
        if tuple(canonical["scopes"]) != APPROVED_ROOT_SCOPES:
            raise RALValidationError(
                "root_authority_scope_mismatch",
                "authority scopes differ from the approved P3-4 set",
            )
        validate_contract("registry-root-authority.schema.json", canonical)
        return cls(canonical_bytes(canonical))


@dataclass(frozen=True)
class RegistryAclObservation(_CanonicalContract):
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistryAclObservation:
        canonical = _canonical_object(value)
        _verify_document_digest(
            canonical, "acl_fingerprint", "registry_acl_digest_mismatch"
        )
        validate_contract("registry-acl-observation.schema.json", canonical)
        return cls(canonical_bytes(canonical))


@dataclass(frozen=True)
class ProductionRegistryManifest(_CanonicalContract):
    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> ProductionRegistryManifest:
        canonical = _canonical_object(value)
        _verify_document_digest(
            canonical, "manifest_digest", "registry_manifest_digest_mismatch"
        )
        validate_contract("production-registry-manifest.schema.json", canonical)
        return cls(canonical_bytes(canonical))


@dataclass(frozen=True)
class RegistryHeadReceipt(_CanonicalContract):
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistryHeadReceipt:
        canonical = _canonical_object(value)
        _verify_document_digest(
            canonical, "control_digest", "control_digest_mismatch"
        )
        validate_contract("registry-head-receipt.schema.json", canonical)
        return cls(canonical_bytes(canonical))


def plan_registry_root(
    *,
    final_root: str,
    candidate_id: str,
    source_commit: str,
    source_package_version: str,
    time_ref: str,
    filesystem: str,
    volume_identity: str,
) -> dict[str, object]:
    exact_root = _require_exact_root(
        final_root, PRODUCTION_REGISTRY_ROOT, "root_target_mismatch"
    )
    try:
        parsed_id = UUID(candidate_id)
    except (ValueError, TypeError, AttributeError) as error:
        raise RALValidationError(
            "candidate_id_invalid", "candidate ID must be UUID4"
        ) from error
    if parsed_id.version != 4 or str(parsed_id) != candidate_id:
        raise RALValidationError(
            "candidate_id_invalid", "candidate ID must be canonical UUID4"
        )
    if filesystem.upper() != "NTFS":
        raise RALValidationError("filesystem_mismatch", "NTFS is required")
    if not _HEX_COMMIT.fullmatch(source_commit):
        raise RALValidationError(
            "source_commit_invalid", "source commit must be a lowercase SHA-1"
        )
    if not source_package_version or not time_ref or not volume_identity:
        raise RALValidationError(
            "root_plan_input_invalid", "plan bindings must be non-empty"
        )
    candidate_name = f".SEDB-RAL.init-{candidate_id}"
    material: dict[str, object] = {
        "schema": "sedb-ral.registry-root-plan/0.1",
        "operation": "registry.root.initialize",
        "final_root": exact_root,
        "registry_parent": PRODUCTION_REGISTRY_PARENT,
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "candidate_root": ntpath.join(PRODUCTION_REGISTRY_PARENT, candidate_name),
        "source_package_name": "sedb-ral",
        "source_package_version": source_package_version,
        "source_commit": source_commit,
        "canonicalization_version": "sedb-ral-json-nfc-codepoint-v1",
        "chain_version": "sedb-ral-ledger-chain-v1",
        "filesystem": "NTFS",
        "volume_identity": volume_identity,
        "time_ref": time_ref,
        "not_claimed": list(_PLAN_NOT_CLAIMED),
    }
    plan = bind_document_digest(material, "plan_digest")
    return RegistryRootPlan.from_dict(plan).to_dict()


def verify_root_authority(
    *, authority: Mapping[str, object], plan_digest: object, exact_root: str
) -> None:
    parsed = RegistryRootAuthority.from_dict(authority).to_dict()
    if parsed["status"] != "active":
        raise RALValidationError(
            "root_authority_inactive", "root authority is not active"
        )
    if parsed["operation_plan_digest"] != plan_digest:
        raise RALValidationError(
            "root_authority_plan_mismatch", "authority binds another plan"
        )
    expected_root = _require_exact_root(
        exact_root, PRODUCTION_REGISTRY_ROOT, "root_authority_target_mismatch"
    )
    if parsed["exact_root"] != expected_root:
        raise RALValidationError(
            "root_authority_target_mismatch", "authority binds another root"
        )


def verify_registry_acl(
    *,
    observation: Mapping[str, object],
    expected_root: str,
    expected_owner_sid: str,
) -> None:
    parsed = RegistryAclObservation.from_dict(observation).to_dict()
    observed_root = _normalized_windows_path(
        parsed["observed_root"], "registry_acl_target_mismatch"
    )
    normalized_expected = _normalized_windows_path(
        expected_root, "registry_acl_target_mismatch"
    )
    if observed_root != normalized_expected:
        raise RALValidationError(
            "registry_acl_target_mismatch", "ACL observation binds another root"
        )
    if parsed["owner_sid"] != expected_owner_sid:
        raise RALValidationError(
            "registry_acl_owner_mismatch", "ACL owner differs"
        )
    if parsed["filesystem"].upper() != "NTFS":
        raise RALValidationError("filesystem_mismatch", "NTFS is required")
    if not parsed["inheritance_protected"]:
        raise RALValidationError(
            "registry_acl_inheritance_enabled", "ACL inheritance is not protected"
        )
    if parsed["reparse_point"]:
        raise RALValidationError(
            "registry_root_reparse_point", "registry root is a reparse point"
        )
    required = {expected_owner_sid, SYSTEM_SID, ADMINISTRATORS_SID}
    if set(parsed["required_full_control_sids"]) != required:
        raise RALValidationError(
            "registry_acl_required_access_missing",
            "required ACL principals differ",
        )
    forbidden = set(parsed["forbidden_write_sids"])
    if forbidden or forbidden & FORBIDDEN_BROAD_SIDS:
        raise RALValidationError(
            "registry_acl_broad_write", "a broad principal retains write access"
        )
