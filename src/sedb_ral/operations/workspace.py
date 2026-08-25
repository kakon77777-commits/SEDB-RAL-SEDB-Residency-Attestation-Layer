from __future__ import annotations

import json
import ntpath
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ..canonical import canonical_bytes, loads_strict, sha256_ref
from ..errors import RALValidationError
from ..registry_root import _reject_alternate_streams
from ..registry_root_contracts import bind_document_digest
from .models import OperationsManifest, OperationsPolicy

PRODUCTION_REGISTRY_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
PRIVATE_RESIDENCE_ROOT = r"D:\AI_RESIDENCE\AI_HOME"
EXPECTED_WORKSPACE_DIRECTORIES = frozenset(
    {
        "policies",
        "active-policy",
        "inbox",
        "requests",
        "receipts",
        "audit",
        "leases",
        "projections",
        "projections/public",
        "staging",
    }
)
_TOP_LEVEL_DIRECTORIES = frozenset(
    {
        "policies",
        "active-policy",
        "inbox",
        "requests",
        "receipts",
        "audit",
        "leases",
        "projections",
        "staging",
    }
)
_PLAN_FIELDS = frozenset(
    {
        "schema",
        "workspace_id",
        "target_root",
        "operations_generation",
        "registry_id",
        "registry_manifest_digest",
        "registry_control_digest",
        "registry_source_tree_digest",
        "policy_digest",
        "time_ref",
        "synthetic_only",
        "plan_digest",
    }
)


@dataclass(frozen=True)
class OperationsWorkspace:
    root: Path
    manifest: OperationsManifest


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("workspace value must remain an object")
    return canonical


def _validate_uuid4(value: str) -> None:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise RALValidationError(
            "operations_workspace_id_invalid", "workspace ID must be UUID4"
        ) from error
    if parsed.version != 4 or str(parsed) != value:
        raise RALValidationError(
            "operations_workspace_id_invalid", "workspace ID must be canonical UUID4"
        )


def _windows_normalized(value: str) -> str:
    return ntpath.normpath(value).casefold()


def _validate_target_boundary(target: Path) -> Path:
    raw = str(target)
    normalized = _windows_normalized(raw)
    production = _windows_normalized(PRODUCTION_REGISTRY_ROOT)
    private = _windows_normalized(PRIVATE_RESIDENCE_ROOT)
    if normalized == production or normalized.startswith(production + "\\"):
        raise RALValidationError(
            "operations_production_activation_not_authorized",
            "R3B-A cannot target the deployed production registry",
        )
    if normalized == private or normalized.startswith(private + "\\"):
        raise RALValidationError(
            "operations_private_boundary", "private Residence target is forbidden"
        )
    if raw.startswith(("\\\\", "\\?\\", "\\.\\")):
        raise RALValidationError(
            "operations_path_unsupported", "network and device paths are forbidden"
        )
    resolved = target.resolve(strict=False)
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise RALValidationError(
                "operations_git_boundary", "operations workspace cannot be inside Git"
            )
    return resolved


def _validate_registry_status(value: Mapping[str, object]) -> None:
    required = {
        "verified",
        "registry_id",
        "manifest_digest",
        "control_digest",
        "tree_digest",
        "ledger_event_count",
        "application_count",
        "resident_count",
        "address_count",
        "private_read_count",
        "network_effect_count",
        "external_effect_count",
    }
    if not required <= set(value) or value["verified"] is not True:
        raise RALValidationError(
            "operations_registry_status_invalid", "registry status is incomplete"
        )
    for name in (
        "ledger_event_count",
        "application_count",
        "resident_count",
        "address_count",
        "private_read_count",
        "network_effect_count",
        "external_effect_count",
    ):
        if value[name] != 0:
            raise RALValidationError(
                "operations_registry_status_invalid",
                "R3B-A workspace requires an empty synthetic registry",
            )


def _verify_plan(value: Mapping[str, object]) -> dict[str, object]:
    canonical = _canonical_object(value)
    if set(canonical) != _PLAN_FIELDS:
        raise RALValidationError(
            "operations_workspace_plan_invalid", "workspace plan fields differ"
        )
    material = dict(canonical)
    actual = material.pop("plan_digest")
    if sha256_ref(material) != actual:
        raise RALValidationError(
            "operations_workspace_plan_digest_mismatch", "workspace plan digest differs"
        )
    if (
        canonical["schema"] != "sedb-ral.operations-workspace-plan/0.1"
        or canonical["synthetic_only"] is not True
    ):
        raise RALValidationError(
            "operations_workspace_plan_invalid", "workspace plan is not synthetic"
        )
    _validate_uuid4(str(canonical["workspace_id"]))
    expected_generation = f"operations-generation:{canonical['workspace_id']}"
    if canonical["operations_generation"] != expected_generation:
        raise RALValidationError(
            "operations_generation_mismatch", "workspace generation differs"
        )
    _validate_target_boundary(Path(str(canonical["target_root"])))
    return canonical


def plan_synthetic_workspace(
    *,
    registry_status: Mapping[str, object],
    policy: OperationsPolicy,
    workspace_id: str,
    time_ref: str,
    target: Path,
) -> dict[str, object]:
    _validate_uuid4(workspace_id)
    _validate_registry_status(registry_status)
    resolved = _validate_target_boundary(Path(target))
    if not isinstance(time_ref, str) or not time_ref:
        raise RALValidationError(
            "operations_time_ref_invalid", "workspace time ref is required"
        )
    material: dict[str, object] = {
        "schema": "sedb-ral.operations-workspace-plan/0.1",
        "workspace_id": workspace_id,
        "target_root": str(resolved),
        "operations_generation": f"operations-generation:{workspace_id}",
        "registry_id": registry_status["registry_id"],
        "registry_manifest_digest": registry_status["manifest_digest"],
        "registry_control_digest": registry_status["control_digest"],
        "registry_source_tree_digest": registry_status["tree_digest"],
        "policy_digest": policy.digest,
        "time_ref": time_ref,
        "synthetic_only": True,
    }
    return bind_document_digest(material, "plan_digest")


def _policy_filename(policy_digest: str) -> str:
    return f"policy-{policy_digest.rsplit(':', 1)[-1][:24]}.json"


def _write_new_json(path: Path, value: Mapping[str, object]) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(canonical_bytes(dict(value)))
    except FileExistsError as error:
        raise RALValidationError(
            "operations_workspace_exists", "workspace output already exists"
        ) from error


def _activation_material(
    *,
    sequence: int,
    generation: str,
    policy_digest: str,
    previous_control_digest: str | None,
    time_ref: str,
) -> dict[str, object]:
    return {
        "schema": "sedb-ral.operations-policy-activation/0.1",
        "control_sequence": sequence,
        "operations_generation": generation,
        "policy_digest": policy_digest,
        "previous_control_digest": previous_control_digest,
        "activated_time_ref": time_ref,
        "not_claimed": [
            "production_activation",
            "registrar_authority",
            "private_access",
        ],
    }


def initialize_synthetic_workspace(
    plan: Mapping[str, object], policy: OperationsPolicy
) -> OperationsWorkspace:
    canonical_plan = _verify_plan(plan)
    if canonical_plan["policy_digest"] != policy.digest:
        raise RALValidationError(
            "operations_policy_digest_mismatch", "plan binds another policy"
        )
    target = Path(str(canonical_plan["target_root"]))
    if target.exists():
        raise RALValidationError(
            "operations_workspace_exists", "operations target already exists"
        )
    if not target.parent.is_dir():
        raise RALValidationError(
            "operations_workspace_parent_unavailable",
            "operations parent is unavailable",
        )
    target.mkdir()
    for relative in sorted(
        EXPECTED_WORKSPACE_DIRECTORIES,
        key=lambda item: (item.count("/"), item),
    ):
        (target / relative).mkdir()

    policy_path = target / "policies" / _policy_filename(policy.digest)
    _write_new_json(policy_path, policy.to_dict())
    activation = bind_document_digest(
        _activation_material(
            sequence=0,
            generation=str(canonical_plan["operations_generation"]),
            policy_digest=policy.digest,
            previous_control_digest=None,
            time_ref=str(canonical_plan["time_ref"]),
        ),
        "control_digest",
    )
    _write_new_json(target / "active-policy/00000000000000000000.json", activation)
    manifest_value = bind_document_digest(
        {
            "schema": "sedb-ral.registrar-operations-manifest/0.1",
            "operations_generation": canonical_plan["operations_generation"],
            "registry_id": canonical_plan["registry_id"],
            "registry_manifest_digest": canonical_plan["registry_manifest_digest"],
            "registry_control_digest": canonical_plan["registry_control_digest"],
            "registry_source_tree_digest": canonical_plan[
                "registry_source_tree_digest"
            ],
            "policy_activation_ref": "active-policy/00000000000000000000.json",
            "synthetic_only": True,
            "production_activation": False,
            "fabric_schema_pins": [],
            "created_time_ref": canonical_plan["time_ref"],
            "not_claimed": [
                "production_activation",
                "identity_proof",
                "private_access",
                "federation",
                "deployment",
            ],
        },
        "manifest_digest",
    )
    manifest = OperationsManifest.from_dict(manifest_value)
    _write_new_json(target / "OPERATIONS-MANIFEST.json", manifest.to_dict())
    return verify_operations_workspace(
        target,
        expected_generation=str(canonical_plan["operations_generation"]),
        registry_status={
            "verified": True,
            "registry_id": canonical_plan["registry_id"],
            "manifest_digest": canonical_plan["registry_manifest_digest"],
            "control_digest": canonical_plan["registry_control_digest"],
            "tree_digest": canonical_plan["registry_source_tree_digest"],
            "ledger_event_count": 0,
            "application_count": 0,
            "resident_count": 0,
            "address_count": 0,
            "private_read_count": 0,
            "network_effect_count": 0,
            "external_effect_count": 0,
        },
    )


def _is_reparse(path: Path) -> bool:
    stat = path.lstat()
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _walk_workspace(root: Path) -> tuple[list[Path], list[Path]]:
    directories: list[Path] = []
    files: list[Path] = []
    for current, names, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        if _is_reparse(current_path):
            raise RALValidationError(
                "operations_workspace_reparse_point", "workspace contains reparse point"
            )
        folded = [item.casefold() for item in names + filenames]
        if len(folded) != len(set(folded)):
            raise RALValidationError(
                "operations_workspace_casefold_collision",
                "workspace names collide by case",
            )
        for name in names:
            path = current_path / name
            if _is_reparse(path):
                raise RALValidationError(
                    "operations_workspace_reparse_point",
                    "workspace contains reparse point",
                )
            directories.append(path)
        for name in filenames:
            path = current_path / name
            if _is_reparse(path):
                raise RALValidationError(
                    "operations_workspace_reparse_point",
                    "workspace contains reparse point",
                )
            if path.stat().st_nlink != 1:
                raise RALValidationError(
                    "operations_workspace_hard_link", "workspace contains hard link"
                )
            files.append(path)
    _reject_alternate_streams(files)
    return directories, files


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(code, "operations JSON cannot be read") from error
    if not isinstance(value, dict):
        raise RALValidationError(code, "operations JSON must be an object")
    return value


def _verify_activation(value: Mapping[str, object]) -> dict[str, object]:
    canonical = _canonical_object(value)
    expected = {
        "schema",
        "control_sequence",
        "operations_generation",
        "policy_digest",
        "previous_control_digest",
        "activated_time_ref",
        "not_claimed",
        "control_digest",
    }
    if set(canonical) != expected:
        raise RALValidationError(
            "operations_policy_activation_invalid", "activation fields differ"
        )
    material = dict(canonical)
    actual = material.pop("control_digest")
    if sha256_ref(material) != actual:
        raise RALValidationError(
            "operations_policy_activation_digest_mismatch",
            "activation digest differs",
        )
    if canonical["schema"] != "sedb-ral.operations-policy-activation/0.1":
        raise RALValidationError(
            "operations_policy_activation_invalid", "activation schema differs"
        )
    return canonical


def verify_operations_workspace(
    root: Path,
    *,
    expected_generation: str,
    registry_status: Mapping[str, object],
) -> OperationsWorkspace:
    selected = _validate_target_boundary(Path(root))
    if not selected.is_dir() or _is_reparse(selected):
        raise RALValidationError(
            "operations_workspace_unavailable", "operations workspace unavailable"
        )
    _validate_registry_status(registry_status)
    directories, _files = _walk_workspace(selected)
    top_directories = {path.name for path in selected.iterdir() if path.is_dir()}
    top_files = {path.name for path in selected.iterdir() if path.is_file()}
    relative_directories = {
        path.relative_to(selected).as_posix() for path in directories
    }
    if (
        top_directories != _TOP_LEVEL_DIRECTORIES
        or top_files != {"OPERATIONS-MANIFEST.json"}
        or not EXPECTED_WORKSPACE_DIRECTORIES <= relative_directories
    ):
        raise RALValidationError(
            "operations_workspace_layout_mismatch", "workspace layout differs"
        )
    manifest = OperationsManifest.from_dict(
        _read_object(
            selected / "OPERATIONS-MANIFEST.json",
            "operations_manifest_invalid_json",
        )
    )
    manifest_value = manifest.to_dict()
    if manifest_value["operations_generation"] != expected_generation:
        raise RALValidationError(
            "operations_generation_mismatch", "operations generation differs"
        )
    binding = (
        ("registry_id", "registry_id"),
        ("registry_manifest_digest", "manifest_digest"),
        ("registry_control_digest", "control_digest"),
        ("registry_source_tree_digest", "tree_digest"),
    )
    if any(
        manifest_value[manifest_name] != registry_status[status_name]
        for manifest_name, status_name in binding
    ):
        raise RALValidationError(
            "operations_registry_binding_mismatch",
            "workspace binds another registry status",
        )

    policy_files = sorted((selected / "policies").glob("policy-*.json"))
    if not policy_files:
        raise RALValidationError(
            "operations_workspace_layout_mismatch", "workspace has no policy"
        )
    policies = {
        OperationsPolicy.from_dict(
            _read_object(path, "operations_policy_invalid_json")
        ).digest: path
        for path in policy_files
    }
    activation_files = sorted((selected / "active-policy").glob("*.json"))
    if not activation_files:
        raise RALValidationError(
            "operations_workspace_layout_mismatch", "workspace has no activation"
        )
    previous: str | None = None
    for sequence, path in enumerate(activation_files):
        if path.name != f"{sequence:020d}.json":
            raise RALValidationError(
                "operations_policy_sequence_mismatch", "activation sequence differs"
            )
        activation = _verify_activation(
            _read_object(path, "operations_policy_activation_invalid_json")
        )
        if (
            activation["control_sequence"] != sequence
            or activation["operations_generation"] != expected_generation
            or activation["previous_control_digest"] != previous
            or activation["policy_digest"] not in policies
        ):
            raise RALValidationError(
                "operations_policy_sequence_mismatch", "activation chain differs"
            )
        previous = str(activation["control_digest"])
    return OperationsWorkspace(root=selected, manifest=manifest)


def activate_policy(
    workspace: OperationsWorkspace,
    policy: OperationsPolicy,
    *,
    expected_active_sequence: int,
) -> dict[str, object]:
    activation_root = workspace.root / "active-policy"
    activation_files = sorted(activation_root.glob("*.json"))
    current_sequence = len(activation_files) - 1
    if current_sequence != expected_active_sequence:
        raise RALValidationError(
            "operations_policy_sequence_mismatch", "active sequence changed"
        )
    previous = _verify_activation(
        _read_object(activation_files[-1], "operations_policy_activation_invalid_json")
    )
    policy_path = workspace.root / "policies" / _policy_filename(policy.digest)
    if not policy_path.exists():
        _write_new_json(policy_path, policy.to_dict())
    sequence = current_sequence + 1
    receipt = bind_document_digest(
        _activation_material(
            sequence=sequence,
            generation=str(workspace.manifest.to_dict()["operations_generation"]),
            policy_digest=policy.digest,
            previous_control_digest=str(previous["control_digest"]),
            time_ref=str(workspace.manifest.to_dict()["created_time_ref"]),
        ),
        "control_digest",
    )
    _write_new_json(activation_root / f"{sequence:020d}.json", receipt)
    return receipt
