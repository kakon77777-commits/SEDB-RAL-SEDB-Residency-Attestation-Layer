from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from .canonical import sha256_ref
from .errors import RALValidationError
from .registry_root import (
    RegistryStorage,
    _read_object,
    _reject_alternate_streams,
    _reject_private_markers,
    _walk,
    _write_new_json,
    registry_root_status,
)
from .registry_root_contracts import (
    PRODUCTION_REGISTRY_ROOT,
    bind_document_digest,
    verify_root_authority,
)


def _uuid4(value: str, code: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise RALValidationError(code, "identifier must be canonical UUID4") from error
    if parsed.version != 4 or str(parsed) != value:
        raise RALValidationError(code, "identifier must be canonical UUID4")
    return value


def _storage(value: RegistryStorage | None) -> RegistryStorage:
    return value if value is not None else RegistryStorage.production()


def _validate_root(value: str) -> None:
    if value != PRODUCTION_REGISTRY_ROOT:
        raise RALValidationError(
            "root_target_mismatch", "recovery target differs from production root"
        )


def _included(relative: str) -> bool:
    return not relative.startswith(("checkpoints/", "rehearsals/"))


def _source_material(root: Path) -> dict[str, object]:
    directories, files = _walk(root)
    _reject_alternate_streams(files)
    _reject_private_markers(root, files)
    return {
        "directories": sorted(
            relative
            for path in directories
            if _included(relative := path.relative_to(root).as_posix())
        ),
        "files": {
            relative: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
            if _included(relative := path.relative_to(root).as_posix())
        },
    }


def _manifest_bytes(material: Mapping[str, object]) -> bytes:
    directories = material["directories"]
    files = material["files"]
    if not isinstance(directories, list) or not isinstance(files, Mapping):
        raise RALValidationError(
            "versioned_checkpoint_manifest_mismatch",
            "versioned checkpoint material is invalid",
        )
    lines = [f"DIR  {name}" for name in directories]
    lines.extend(f"{digest}  {name}" for name, digest in sorted(files.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _copy_file_new(source: Path, destination: Path) -> None:
    if source.is_symlink() or source.stat().st_nlink != 1:
        raise RALValidationError(
            "checkpoint_link_detected", "checkpoint inputs must be copied values"
        )
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            while block := input_stream.read(1024 * 1024):
                output_stream.write(block)
    except FileExistsError as error:
        raise RALValidationError(
            "recovery_output_exists", "recovery output already exists"
        ) from error
    except OSError as error:
        raise RALValidationError(
            "recovery_copy_failed", "recovery value copy failed"
        ) from error


def _copy_material(source: Path, destination: Path, material: Mapping[str, object]) -> None:
    destination.mkdir()
    directories = material["directories"]
    files = material["files"]
    if not isinstance(directories, list) or not isinstance(files, Mapping):
        raise RALValidationError(
            "versioned_checkpoint_manifest_mismatch", "snapshot material is invalid"
        )
    for relative in sorted(directories, key=lambda item: (item.count("/"), item)):
        (destination / relative).mkdir()
    for relative in sorted(files):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_new(source / relative, target)


def _verify_authority(
    authority: Mapping[str, object], status: Mapping[str, object]
) -> None:
    verify_root_authority(
        authority=authority,
        plan_digest=status["plan_digest"],
        exact_root=PRODUCTION_REGISTRY_ROOT,
    )


def create_versioned_registry_checkpoint(
    *,
    root: str,
    checkpoint_id: str,
    phase: str,
    authority: Mapping[str, object],
    time_ref: str,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    _validate_root(root)
    _uuid4(checkpoint_id, "checkpoint_id_invalid")
    if phase not in {"pre_activation", "post_activation"}:
        raise RALValidationError(
            "versioned_checkpoint_phase_invalid", "checkpoint phase is invalid"
        )
    if not isinstance(time_ref, str) or not time_ref:
        raise RALValidationError("time_ref_invalid", "time reference is required")
    selected = _storage(storage)
    status = registry_root_status(storage=selected)
    _verify_authority(authority, status)
    before_material = _source_material(selected.final)
    before_digest = sha256_ref(before_material)
    checkpoint_root = selected.final / f"checkpoints/checkpoint-{checkpoint_id}"
    receipt_path = selected.final / f"evidence/checkpoints/checkpoint-{checkpoint_id}.json"
    if checkpoint_root.exists() or receipt_path.exists():
        raise RALValidationError("checkpoint_exists", "checkpoint output exists")
    checkpoint_root.mkdir()
    snapshot = checkpoint_root / "snapshot"
    _copy_material(selected.final, snapshot, before_material)
    if _source_material(selected.final) != before_material:
        raise RALValidationError(
            "versioned_checkpoint_source_changed",
            "production source changed during checkpoint",
        )
    manifest = _manifest_bytes(before_material)
    (checkpoint_root / "MANIFEST.sha256").write_bytes(manifest)
    checkpoint = bind_document_digest(
        {
            "schema": "sedb-ral.versioned-registry-checkpoint/0.1",
            "checkpoint_id": f"checkpoint:{checkpoint_id}",
            "phase": phase,
            "registry_id": status["registry_id"],
            "registry_generation_digest": status["registry_generation_digest"],
            "source_snapshot_digest": before_digest,
            "source_control_digest": status["control_digest"],
            "source_event_count": status["ledger_event_count"],
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "snapshot_root": "snapshot",
            "created_time_ref": time_ref,
            "storage_scope": "same_volume_local",
            "not_claimed": ["offsite_backup", "private_backup", "production_mutation"],
        },
        "checkpoint_digest",
    )
    _write_new_json(checkpoint_root / "CHECKPOINT.json", checkpoint)
    verified = verify_versioned_registry_checkpoint(checkpoint_root)
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.versioned-registry-checkpoint-receipt/0.1",
            "checkpoint_id": f"checkpoint:{checkpoint_id}",
            "phase": phase,
            "registry_id": status["registry_id"],
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "registry_generation_digest": status["registry_generation_digest"],
            "created_time_ref": time_ref,
            "not_claimed": ["offsite_backup", "private_backup"],
        },
        "receipt_digest",
    )
    receipt_path.parent.mkdir(exist_ok=True)
    _write_new_json(receipt_path, receipt)
    return {
        **verified,
        "checkpoint_path": str(checkpoint_root),
        "evidence_receipt_digest": receipt["receipt_digest"],
    }


def verify_versioned_registry_checkpoint(checkpoint_root: Path) -> dict[str, object]:
    root = Path(checkpoint_root)
    if not root.is_dir():
        raise RALValidationError("checkpoint_unavailable", "checkpoint is unavailable")
    checkpoint = _read_object(root / "CHECKPOINT.json", "checkpoint_invalid_json")
    material = dict(checkpoint)
    actual_digest = material.pop("checkpoint_digest", None)
    if actual_digest != sha256_ref(material):
        raise RALValidationError(
            "versioned_checkpoint_digest_mismatch", "checkpoint digest differs"
        )
    snapshot = root / "snapshot"
    observed = _source_material(snapshot)
    manifest = (root / "MANIFEST.sha256").read_bytes()
    if (
        manifest != _manifest_bytes(observed)
        or hashlib.sha256(manifest).hexdigest() != checkpoint.get("manifest_sha256")
        or sha256_ref(observed) != checkpoint.get("source_snapshot_digest")
    ):
        raise RALValidationError(
            "versioned_checkpoint_manifest_mismatch",
            "checkpoint snapshot differs from manifest",
        )
    snapshot_status = registry_root_status(
        storage=RegistryStorage(parent=snapshot.parent, final=snapshot, synthetic_mode=True)
    )
    if (
        snapshot_status["registry_id"] != checkpoint.get("registry_id")
        or snapshot_status["registry_generation_digest"]
        != checkpoint.get("registry_generation_digest")
    ):
        raise RALValidationError(
            "versioned_checkpoint_manifest_mismatch",
            "checkpoint status differs from metadata",
        )
    return {
        "schema": "sedb-ral.versioned-registry-checkpoint-verification/0.1",
        "verified": True,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "registry_id": checkpoint["registry_id"],
        "registry_generation_digest": checkpoint["registry_generation_digest"],
        "source_snapshot_digest": checkpoint["source_snapshot_digest"],
        "snapshot_digest": sha256_ref(observed),
        "phase": checkpoint["phase"],
        "storage_scope": "same_volume_local",
    }


def _checkpoint_under_root(path: Path, storage: RegistryStorage) -> Path:
    try:
        resolved = path.resolve(strict=True)
        allowed = (storage.final / "checkpoints").resolve(strict=True)
        resolved.relative_to(allowed)
    except (OSError, ValueError) as error:
        raise RALValidationError(
            "checkpoint_path_escape", "checkpoint is outside production root"
        ) from error
    if resolved.parent != allowed:
        raise RALValidationError(
            "checkpoint_path_escape", "checkpoint must be an immediate child"
        )
    return resolved


def _write_versioned_evidence(
    root: Path, family: str, identifier: str, value: Mapping[str, object]
) -> None:
    target = root / f"evidence/{family}/{identifier}.json"
    target.parent.mkdir(exist_ok=True)
    _write_new_json(target, value)


def rehearse_versioned_registry_restore(
    *,
    root: str,
    checkpoint_root: Path,
    rehearsal_id: str,
    authority: Mapping[str, object],
    time_ref: str,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    _validate_root(root)
    _uuid4(rehearsal_id, "rehearsal_id_invalid")
    selected = _storage(storage)
    before = registry_root_status(storage=selected)
    _verify_authority(authority, before)
    checkpoint_path = _checkpoint_under_root(Path(checkpoint_root), selected)
    checkpoint = verify_versioned_registry_checkpoint(checkpoint_path)
    target = selected.final / f"rehearsals/restore-{rehearsal_id}"
    if target.exists():
        raise RALValidationError("restore_rehearsal_exists", "restore exists")
    target.mkdir()
    restored = target / "restored"
    source_material = _source_material(checkpoint_path / "snapshot")
    _copy_material(checkpoint_path / "snapshot", restored, source_material)
    restored_material = _source_material(restored)
    after = registry_root_status(storage=selected)
    if restored_material != source_material or (
        after["registry_generation_digest"] != before["registry_generation_digest"]
    ):
        raise RALValidationError(
            "versioned_restore_mismatch", "restore or production digest differs"
        )
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.versioned-registry-restore-receipt/0.1",
            "rehearsal_id": f"restore:{rehearsal_id}",
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "source_snapshot_digest": checkpoint["source_snapshot_digest"],
            "restored_snapshot_digest": sha256_ref(restored_material),
            "production_generation_before": before["registry_generation_digest"],
            "production_generation_after": after["registry_generation_digest"],
            "restored": True,
            "created_time_ref": time_ref,
            "not_claimed": ["production_mutation", "offsite_recovery", "private_restore"],
        },
        "receipt_digest",
    )
    _write_new_json(target / "RESTORE-RECEIPT.json", receipt)
    _write_versioned_evidence(selected.final, "restores", f"restore-{rehearsal_id}", receipt)
    return {**receipt, "rehearsal_path": str(target)}


def rehearse_versioned_registry_rollback(
    *,
    root: str,
    checkpoint_root: Path,
    rehearsal_id: str,
    authority: Mapping[str, object],
    time_ref: str,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    _validate_root(root)
    _uuid4(rehearsal_id, "rehearsal_id_invalid")
    selected = _storage(storage)
    before = registry_root_status(storage=selected)
    _verify_authority(authority, before)
    checkpoint_path = _checkpoint_under_root(Path(checkpoint_root), selected)
    checkpoint = verify_versioned_registry_checkpoint(checkpoint_path)
    target = selected.final / f"rehearsals/rollback-{rehearsal_id}"
    if target.exists():
        raise RALValidationError("rollback_rehearsal_exists", "rollback exists")
    target.mkdir()
    source = checkpoint_path / "snapshot"
    source_material = _source_material(source)
    corrupted = target / "corrupted"
    fresh = target / "fresh"
    _copy_material(source, corrupted, source_material)
    manifest = corrupted / "registry-manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    try:
        if _source_material(corrupted) != source_material:
            raise RALValidationError(
                "versioned_checkpoint_manifest_mismatch",
                "corrupted snapshot differs",
            )
    except RALValidationError as error:
        red_code = error.code
    else:
        raise RALValidationError(
            "rollback_red_control_failed", "corruption was not detected"
        )
    _copy_material(source, fresh, source_material)
    fresh_material = _source_material(fresh)
    after = registry_root_status(storage=selected)
    if fresh_material != source_material or (
        after["registry_generation_digest"] != before["registry_generation_digest"]
    ):
        raise RALValidationError(
            "versioned_rollback_mismatch", "rollback proof differs"
        )
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.versioned-registry-rollback-receipt/0.1",
            "rehearsal_id": f"rollback:{rehearsal_id}",
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "red_control_error_code": red_code,
            "fresh_restore_digest": sha256_ref(fresh_material),
            "production_generation_before": before["registry_generation_digest"],
            "production_generation_after": after["registry_generation_digest"],
            "passed": True,
            "created_time_ref": time_ref,
            "not_claimed": ["production_mutation", "offsite_recovery", "private_restore"],
        },
        "receipt_digest",
    )
    _write_new_json(target / "ROLLBACK-RECEIPT.json", receipt)
    _write_versioned_evidence(selected.final, "rollbacks", f"rollback-{rehearsal_id}", receipt)
    return {**receipt, "rehearsal_path": str(target)}
