from __future__ import annotations

from collections.abc import Mapping
import ntpath
from pathlib import Path

from .canonical import sha256_ref
from .errors import RALValidationError
from .production_operations_contracts import (
    ProductionOperationsActivationCommit,
    ProductionOperationsActivationReceipt,
    ProductionOperationsAuthority,
    ProductionOperationsManifest,
    ProductionOperationsPlan,
    ProductionOperationsPolicy,
    RegistryExtensionIndex,
    verify_production_operations_authority,
)
from .registry_root import (
    RegistryStorage,
    _rename_no_replace,
    _read_object,
    _reject_alternate_streams,
    _reject_private_markers,
    _relative,
    _storage,
    _tree_digest,
    _verify_bound_receipt,
    _walk,
    _write_new_json,
    registry_root_status,
)
from .registry_root_contracts import (
    PRODUCTION_REGISTRY_PARENT,
    bind_document_digest,
    verify_registry_acl,
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


def _candidate_root(
    storage: RegistryStorage, plan: Mapping[str, object]
) -> Path:
    return storage.parent / str(plan["candidate_name"])


def _logical_candidate_root(plan: Mapping[str, object]) -> str:
    return ntpath.join(PRODUCTION_REGISTRY_PARENT, str(plan["candidate_name"]))


def _verify_live_binding(
    plan: Mapping[str, object], status: Mapping[str, object]
) -> None:
    bindings = (
        ("registry_id", "registry_id"),
        ("registry_manifest_digest", "manifest_digest"),
        ("registry_control_digest", "control_digest"),
        ("base_tree_digest", "tree_digest"),
    )
    if any(plan[left] != status[right] for left, right in bindings):
        raise RALValidationError(
            "production_operations_registry_binding_mismatch",
            "production registry changed after planning",
        )
    required = plan["required_counts"]
    if not isinstance(required, Mapping) or any(
        status.get(name) != expected for name, expected in required.items()
    ):
        raise RALValidationError(
            "production_operations_registry_not_empty",
            "production registry counts differ from plan",
        )


def _activation_material(plan: Mapping[str, object], policy_digest: str):
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-policy-activation/0.1",
            "control_sequence": 0,
            "operations_generation": plan["operations_generation"],
            "policy_digest": policy_digest,
            "previous_control_digest": None,
            "activated_time_ref": plan["time_ref"],
            "execution_enabled": False,
            "not_claimed": ["registrar_authority", "resident_registration"],
        },
        "control_digest",
    )


def prepare_production_operations_candidate(
    plan: Mapping[str, object],
    authority: Mapping[str, object],
    acl_observation: Mapping[str, object],
    policy: Mapping[str, object],
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    parsed_plan = ProductionOperationsPlan.from_dict(plan).to_dict()
    parsed_authority = verify_production_operations_authority(
        authority,
        plan_digest=str(parsed_plan["plan_digest"]),
        exact_root=str(parsed_plan["final_root"]),
    )
    parsed_policy = ProductionOperationsPolicy.from_dict(policy).to_dict()
    if parsed_policy["policy_digest"] != parsed_plan["policy_digest"]:
        raise RALValidationError(
            "production_operations_policy_mismatch",
            "production policy differs from plan",
        )
    selected = _storage(storage)
    live_status = registry_root_status(storage=selected)
    _verify_live_binding(parsed_plan, live_status)
    if live_status["extensions_status"] != "absent" or (
        selected.final / "extensions"
    ).exists():
        raise RALValidationError(
            "production_operations_extension_exists",
            "production operations extension already exists",
        )
    if acl_observation.get("acl_fingerprint") != parsed_plan["acl_fingerprint"]:
        raise RALValidationError(
            "production_operations_acl_mismatch",
            "candidate ACL fingerprint differs from plan",
        )
    if (
        acl_observation.get("volume_identity") != parsed_plan["volume_identity"]
        or str(acl_observation.get("filesystem", "")).upper()
        != str(parsed_plan["filesystem"]).upper()
    ):
        raise RALValidationError(
            "production_operations_volume_mismatch",
            "candidate ACL observation is on another filesystem or volume",
        )
    verify_registry_acl(
        observation=acl_observation,
        expected_root=_logical_candidate_root(parsed_plan),
        expected_owner_sid=str(parsed_plan["expected_owner_sid"]),
    )
    candidate = _candidate_root(selected, parsed_plan)
    if not candidate.is_dir() or any(candidate.iterdir()):
        raise RALValidationError(
            "production_operations_candidate_not_empty",
            "production operations candidate must be an existing empty directory",
        )
    version_root = candidate / "extensions/registrar-operations/v1"
    for relative in sorted(
        EXPECTED_EXTENSION_DIRECTORIES,
        key=lambda item: (item.count("/"), item),
    ):
        (candidate / "extensions" / relative).mkdir(parents=True, exist_ok=True)
    manifest = bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-extension-manifest/0.1",
            "extension_kind": "registrar-operations",
            "extension_version": "v1",
            "extension_ref": "extensions/registrar-operations/v1",
            "operations_generation": parsed_plan["operations_generation"],
            "registry_id": parsed_plan["registry_id"],
            "registry_manifest_digest": parsed_plan["registry_manifest_digest"],
            "registry_control_digest": parsed_plan["registry_control_digest"],
            "base_tree_digest": parsed_plan["base_tree_digest"],
            "dormant_policy_ref": "policies/policy-production-dormant-v1.json",
            "dormant_policy_digest": parsed_policy["policy_digest"],
            "activation_commit_ref": "ACTIVATION-COMMIT.json",
            "created_time_ref": parsed_plan["time_ref"],
            "production_activation": True,
            "execution_enabled": False,
            "not_claimed": [
                "resident_registration",
                "ledger_append",
                "private_access",
            ],
        },
        "manifest_digest",
    )
    ProductionOperationsManifest.from_dict(manifest)
    commit = bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-activation-commit/0.1",
            "candidate_id": parsed_plan["candidate_id"],
            "plan_digest": parsed_plan["plan_digest"],
            "authority_digest": parsed_authority["authority_digest"],
            "manifest_digest": manifest["manifest_digest"],
            "policy_digest": parsed_policy["policy_digest"],
            "pre_checkpoint_digest": parsed_plan["pre_checkpoint_digest"],
            "committed_time_ref": parsed_plan["time_ref"],
            "not_claimed": [
                "published",
                "ledger_append",
                "resident_registration",
                "private_access",
            ],
        },
        "commit_digest",
    )
    ProductionOperationsActivationCommit.from_dict(commit)
    index = bind_document_digest(
        {
            "schema": "sedb-ral.registry-extension-index/0.1",
            "index_sequence": 0,
            "extension_kind": "registrar-operations",
            "extension_version": "v1",
            "extension_ref": "extensions/registrar-operations/v1",
            "extension_manifest_digest": manifest["manifest_digest"],
            "activation_commit_digest": commit["commit_digest"],
            "operations_generation": parsed_plan["operations_generation"],
            "previous_index_digest": None,
            "source_commit": parsed_plan["source_commit"],
            "source_package_version": parsed_plan["source_package_version"],
            "pre_checkpoint_digest": parsed_plan["pre_checkpoint_digest"],
            "recorded_time_ref": parsed_plan["time_ref"],
            "not_claimed": [
                "ledger_head",
                "resident_registration",
                "authority_grant",
            ],
        },
        "index_digest",
    )
    RegistryExtensionIndex.from_dict(index)
    _write_new_json(
        candidate / "extensions/index/00000000000000000000.json", index
    )
    _write_new_json(version_root / "EXTENSION-MANIFEST.json", manifest)
    _write_new_json(version_root / "ACTIVATION-COMMIT.json", commit)
    _write_new_json(
        version_root / "policies/policy-production-dormant-v1.json", parsed_policy
    )
    _write_new_json(
        version_root / "active-policy/00000000000000000000.json",
        _activation_material(parsed_plan, str(parsed_policy["policy_digest"])),
    )
    verified = verify_production_operations_extension(
        candidate, receipt_required=False
    )
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-candidate-prepared/0.1",
            "candidate_id": parsed_plan["candidate_id"],
            "plan_digest": parsed_plan["plan_digest"],
            "candidate_tree_digest": _tree_digest(candidate / "extensions"),
            "extension_index_digest": verified["extension_index_digest"],
            "effects": {
                "production_writes": 0,
                "ledger_events": 0,
                "real_applicants": 0,
                "private_reads": 0,
                "network_calls": 0,
            },
            "not_claimed": ["published", "resident_registration"],
        },
        "prepared_digest",
    )


def verify_production_operations_candidate(
    plan: Mapping[str, object],
    prepared: Mapping[str, object],
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    parsed_plan = ProductionOperationsPlan.from_dict(plan).to_dict()
    _verify_bound_receipt(
        prepared,
        "prepared_digest",
        "production_operations_prepared_digest_mismatch",
    )
    if (
        prepared.get("candidate_id") != parsed_plan["candidate_id"]
        or prepared.get("plan_digest") != parsed_plan["plan_digest"]
    ):
        raise RALValidationError(
            "production_operations_prepared_mismatch",
            "prepared candidate binds another plan",
        )
    selected = _storage(storage)
    candidate = _candidate_root(selected, parsed_plan)
    extension = verify_production_operations_extension(
        candidate, receipt_required=False
    )
    tree_digest = _tree_digest(candidate / "extensions")
    if tree_digest != prepared.get("candidate_tree_digest"):
        raise RALValidationError(
            "production_operations_candidate_tree_digest_mismatch",
            "production operations candidate tree differs",
        )
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-candidate-verification/0.1",
            "verified": True,
            "candidate_id": parsed_plan["candidate_id"],
            "plan_digest": parsed_plan["plan_digest"],
            "candidate_tree_digest": tree_digest,
            "extension_index_digest": extension["extension_index_digest"],
            "not_claimed": ["published", "resident_registration"],
        },
        "verification_digest",
    )


def publish_production_operations_candidate(
    plan: Mapping[str, object],
    verification: Mapping[str, object],
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    parsed_plan = ProductionOperationsPlan.from_dict(plan).to_dict()
    _verify_bound_receipt(
        verification,
        "verification_digest",
        "production_operations_verification_digest_mismatch",
    )
    if (
        verification.get("verified") is not True
        or verification.get("candidate_id") != parsed_plan["candidate_id"]
        or verification.get("plan_digest") != parsed_plan["plan_digest"]
    ):
        raise RALValidationError(
            "production_operations_verification_mismatch",
            "verification binds another candidate",
        )
    selected = _storage(storage)
    live_status = registry_root_status(storage=selected)
    _verify_live_binding(parsed_plan, live_status)
    if live_status["extensions_status"] != "absent" or (
        selected.final / "extensions"
    ).exists():
        raise RALValidationError(
            "production_operations_extension_exists",
            "production operations extension already exists",
        )
    candidate = _candidate_root(selected, parsed_plan)
    source = candidate / "extensions"
    if not source.is_dir():
        raise RALValidationError(
            "production_operations_candidate_unavailable",
            "production operations candidate is unavailable",
        )
    current_digest = _tree_digest(source)
    if current_digest != verification.get("candidate_tree_digest"):
        raise RALValidationError(
            "production_operations_candidate_tree_digest_mismatch",
            "production operations candidate changed after verification",
        )
    verify_production_operations_extension(candidate, receipt_required=False)
    _rename_no_replace(source, selected.final / "extensions")
    status = registry_root_status(storage=selected)
    if status["extensions_status"] != "active_dormant_unreceipted":
        raise RALValidationError(
            "production_operations_publication_unverified",
            "published production operations extension did not verify",
        )
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-publication-result/0.1",
            "published": True,
            "candidate_id": parsed_plan["candidate_id"],
            "plan_digest": parsed_plan["plan_digest"],
            "extension_index_digest": status["extension_index_digest"],
            "registry_generation_digest": status["registry_generation_digest"],
            "effects": {
                "ledger_events": 0,
                "residents": 0,
                "private_reads": 0,
                "network_calls": 0,
            },
            "not_claimed": ["resident_registration", "activation_receipted"],
        },
        "publication_digest",
    )


def write_activation_receipt(
    *,
    root: Path,
    plan: Mapping[str, object],
    index: Mapping[str, object],
    observed_time_ref: str,
) -> dict[str, object]:
    parsed_plan = ProductionOperationsPlan.from_dict(plan).to_dict()
    parsed_index = RegistryExtensionIndex.from_dict(index).to_dict()
    if (
        parsed_index["operations_generation"]
        != parsed_plan["operations_generation"]
        or parsed_index["pre_checkpoint_digest"]
        != parsed_plan["pre_checkpoint_digest"]
    ):
        raise RALValidationError(
            "production_operations_activation_receipt_mismatch",
            "activation receipt inputs bind another plan",
        )
    selected = Path(root)
    base = {
        "registry_id": parsed_plan["registry_id"],
        "manifest_digest": parsed_plan["registry_manifest_digest"],
        "control_digest": parsed_plan["registry_control_digest"],
        "tree_digest": parsed_plan["base_tree_digest"],
    }
    generation_digest = registry_generation_digest(
        base, str(parsed_index["index_digest"])
    )
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-activation-receipt/0.1",
            "candidate_id": parsed_plan["candidate_id"],
            "registry_id": parsed_plan["registry_id"],
            "extension_index_digest": parsed_index["index_digest"],
            "registry_generation_digest": generation_digest,
            "observed_final_ref": "extensions/registrar-operations/v1",
            "observed_time_ref": observed_time_ref,
            "not_claimed": [
                "ledger_append",
                "resident_registration",
                "private_access",
            ],
        },
        "receipt_digest",
    )
    ProductionOperationsActivationReceipt.from_dict(receipt)
    receipt_path = (
        selected
        / "evidence"
        / f"operations-extension-activation-{parsed_plan['candidate_id']}.json"
    )
    _write_new_json(receipt_path, receipt)
    return receipt


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
