from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .canonical import sha256_ref
from .errors import RALValidationError
from .production_operations_contracts import (
    ProductionOperationsActivationCommit,
    ProductionOperationsActivationReceipt,
    ProductionOperationsManifest,
    ProductionOperationsPolicy,
    RegistryExtensionIndex,
)
from .registry_root import (
    _read_object,
    _reject_alternate_streams,
    _reject_private_markers,
    _relative,
    _verify_bound_receipt,
    _walk,
)


EXPECTED_EXTENSION_DIRECTORIES = frozenset(
    {
        "index",
        "registrar-operations",
        "registrar-operations/v1",
        "registrar-operations/v1/policies",
        "registrar-operations/v1/active-policy",
        "registrar-operations/v1/inbox",
        "registrar-operations/v1/requests",
        "registrar-operations/v1/receipts",
        "registrar-operations/v1/audit",
        "registrar-operations/v1/leases",
        "registrar-operations/v1/projections",
        "registrar-operations/v1/projections/public",
        "registrar-operations/v1/staging",
    }
)
EXPECTED_EXTENSION_FILES = frozenset(
    {
        "index/00000000000000000000.json",
        "registrar-operations/v1/EXTENSION-MANIFEST.json",
        "registrar-operations/v1/ACTIVATION-COMMIT.json",
        "registrar-operations/v1/policies/policy-production-dormant-v1.json",
        "registrar-operations/v1/active-policy/00000000000000000000.json",
    }
)


def registry_generation_digest(
    base_status: Mapping[str, object], index_digest: str | None
) -> str:
    return sha256_ref(
        {
            "schema": "sedb-ral.registry-generation/0.1",
            "registry_id": base_status["registry_id"],
            "manifest_digest": base_status["manifest_digest"],
            "control_digest": base_status["control_digest"],
            "base_tree_digest": base_status["tree_digest"],
            "extension_index_digest": index_digest,
        }
    )


def _verify_activation(value: Mapping[str, object]) -> dict[str, object]:
    required = {
        "schema",
        "control_sequence",
        "operations_generation",
        "policy_digest",
        "previous_control_digest",
        "activated_time_ref",
        "execution_enabled",
        "not_claimed",
        "control_digest",
    }
    if set(value) != required:
        raise RALValidationError(
            "production_operations_extension_layout_mismatch",
            "production policy activation fields differ",
        )
    _verify_bound_receipt(
        value,
        "control_digest",
        "production_operations_policy_activation_digest_mismatch",
    )
    if (
        value["schema"] != "sedb-ral.production-operations-policy-activation/0.1"
        or value["control_sequence"] != 0
        or value["previous_control_digest"] is not None
        or value["execution_enabled"] is not False
        or value["not_claimed"]
        != ["registrar_authority", "resident_registration"]
    ):
        raise RALValidationError(
            "production_operations_policy_activation_invalid",
            "production policy activation is not dormant genesis",
        )
    return dict(value)


def verify_production_operations_extension(
    root: Path, *, receipt_required: bool = True
) -> dict[str, object]:
    selected = Path(root)
    extension_root = selected / "extensions"
    if not extension_root.is_dir():
        raise RALValidationError(
            "production_operations_extension_unavailable",
            "production operations extension is unavailable",
        )
    directories, files = _walk(extension_root)
    _reject_alternate_streams(files)
    _reject_private_markers(extension_root, files)
    relative_directories = {_relative(path, extension_root) for path in directories}
    relative_files = {_relative(path, extension_root) for path in files}
    if (
        relative_directories != EXPECTED_EXTENSION_DIRECTORIES
        or relative_files != EXPECTED_EXTENSION_FILES
    ):
        raise RALValidationError(
            "production_operations_extension_layout_mismatch",
            "production operations extension layout differs",
        )
    version_root = extension_root / "registrar-operations/v1"
    index = RegistryExtensionIndex.from_dict(
        _read_object(
            extension_root / "index/00000000000000000000.json",
            "registry_extension_index_invalid_json",
        )
    ).to_dict()
    manifest = ProductionOperationsManifest.from_dict(
        _read_object(
            version_root / "EXTENSION-MANIFEST.json",
            "production_operations_manifest_invalid_json",
        )
    ).to_dict()
    commit = ProductionOperationsActivationCommit.from_dict(
        _read_object(
            version_root / "ACTIVATION-COMMIT.json",
            "production_operations_commit_invalid_json",
        )
    ).to_dict()
    policy = ProductionOperationsPolicy.from_dict(
        _read_object(
            version_root / "policies/policy-production-dormant-v1.json",
            "production_operations_policy_invalid_json",
        )
    ).to_dict()
    activation = _verify_activation(
        _read_object(
            version_root / "active-policy/00000000000000000000.json",
            "production_operations_policy_activation_invalid_json",
        )
    )
    if (
        index["extension_manifest_digest"] != manifest["manifest_digest"]
        or index["activation_commit_digest"] != commit["commit_digest"]
        or index["operations_generation"] != manifest["operations_generation"]
        or commit["manifest_digest"] != manifest["manifest_digest"]
        or commit["policy_digest"] != policy["policy_digest"]
        or manifest["dormant_policy_digest"] != policy["policy_digest"]
        or activation["policy_digest"] != policy["policy_digest"]
        or activation["operations_generation"] != manifest["operations_generation"]
    ):
        raise RALValidationError(
            "production_operations_extension_binding_mismatch",
            "production operations extension bindings differ",
        )
    base_status = {
        "registry_id": manifest["registry_id"],
        "manifest_digest": manifest["registry_manifest_digest"],
        "control_digest": manifest["registry_control_digest"],
        "tree_digest": manifest["base_tree_digest"],
    }
    generation_digest = registry_generation_digest(
        base_status, str(index["index_digest"])
    )
    receipt_path = (
        selected
        / "evidence"
        / f"operations-extension-activation-{commit['candidate_id']}.json"
    )
    if not receipt_path.is_file():
        if receipt_required:
            return {
                "extensions_status": "active_dormant_unreceipted",
                "activation_receipt_status": "missing",
                "extension_index_digest": index["index_digest"],
                "operations_generation": manifest["operations_generation"],
                "registry_generation_digest": generation_digest,
                "candidate_id": commit["candidate_id"],
            }
        receipt_status = "not_required"
    else:
        receipt = ProductionOperationsActivationReceipt.from_dict(
            _read_object(
                receipt_path, "production_operations_activation_receipt_invalid_json"
            )
        ).to_dict()
        if (
            receipt["candidate_id"] != commit["candidate_id"]
            or receipt["registry_id"] != manifest["registry_id"]
            or receipt["extension_index_digest"] != index["index_digest"]
            or receipt["registry_generation_digest"] != generation_digest
        ):
            raise RALValidationError(
                "production_operations_activation_receipt_mismatch",
                "activation receipt binds another extension",
            )
        receipt_status = "verified"
    return {
        "extensions_status": "active_dormant",
        "activation_receipt_status": receipt_status,
        "extension_index_digest": index["index_digest"],
        "operations_generation": manifest["operations_generation"],
        "registry_generation_digest": generation_digest,
        "candidate_id": commit["candidate_id"],
    }

