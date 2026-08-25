from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from .canonical import sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .registry_root import (
    EXPECTED_DIRECTORIES,
    EXPECTED_FILES,
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
    ProductionRegistryManifest,
    RegistryHeadReceipt,
    bind_document_digest,
    verify_root_authority,
)

SNAPSHOT_DIRECTORIES = frozenset(
    {
        "ledger",
        "ledger/events",
        "ledger/anchors",
        "control",
        "control/heads",
        "evidence",
    }
)
SNAPSHOT_FILES = EXPECTED_FILES


def _selected_storage(storage: RegistryStorage | None) -> RegistryStorage:
    return storage if storage is not None else RegistryStorage.production()


def _validate_root(root: str) -> None:
    if root != PRODUCTION_REGISTRY_ROOT:
        raise RALValidationError(
            "root_target_mismatch", "recovery target differs from production root"
        )


def _uuid4(value: str, code: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise RALValidationError(code, "identifier must be canonical UUID4") from error
    if parsed.version != 4 or str(parsed) != value:
        raise RALValidationError(code, "identifier must be canonical UUID4")
    return value


def _require_time_ref(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise RALValidationError(
            "time_ref_invalid", "an explicit time reference is required"
        )
    return value


def _raw_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_file_hashes(snapshot: Path) -> dict[str, str]:
    return {
        relative: _raw_hash(snapshot / relative) for relative in sorted(SNAPSHOT_FILES)
    }


def _snapshot_material(snapshot: Path) -> dict[str, object]:
    return {
        "directories": sorted(SNAPSHOT_DIRECTORIES),
        "files": _snapshot_file_hashes(snapshot),
    }


def _source_material_from_snapshot(snapshot: Path) -> dict[str, object]:
    return {
        "directories": sorted(EXPECTED_DIRECTORIES),
        "files": _snapshot_file_hashes(snapshot),
    }


def _manifest_bytes(snapshot: Path) -> bytes:
    lines = ["EMPTY  ledger/anchors/", "EMPTY  ledger/events/"]
    lines.extend(
        f"{digest}  {relative}"
        for relative, digest in _snapshot_file_hashes(snapshot).items()
    )
    return ("\n".join(sorted(lines)) + "\n").encode("utf-8")


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


def _copy_snapshot(source_root: Path, snapshot: Path) -> None:
    snapshot.mkdir()
    for relative in sorted(
        SNAPSHOT_DIRECTORIES, key=lambda value: (value.count("/"), value)
    ):
        (snapshot / relative).mkdir()
    for relative in sorted(SNAPSHOT_FILES):
        _copy_file_new(source_root / relative, snapshot / relative)


def _verify_digest(value: Mapping[str, object], field: str, code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(code, "recovery receipt digest differs")


def _verify_snapshot(snapshot: Path, manifest_bytes: bytes) -> dict[str, object]:
    if not snapshot.is_dir():
        raise RALValidationError(
            "checkpoint_snapshot_missing", "checkpoint snapshot is missing"
        )
    directories, files = _walk(snapshot)
    _reject_alternate_streams(files)
    _reject_private_markers(snapshot, files)
    relative_directories = {
        path.relative_to(snapshot).as_posix() for path in directories
    }
    relative_files = {path.relative_to(snapshot).as_posix() for path in files}
    if (
        relative_directories != SNAPSHOT_DIRECTORIES
        or relative_files != SNAPSHOT_FILES
        or _manifest_bytes(snapshot) != manifest_bytes
    ):
        raise RALValidationError(
            "checkpoint_manifest_digest_mismatch",
            "checkpoint snapshot differs from its manifest",
        )
    manifest = ProductionRegistryManifest.from_dict(
        _read_object(
            snapshot / "registry-manifest.json",
            "checkpoint_manifest_digest_mismatch",
        )
    ).to_dict()
    try:
        head = RegistryHeadReceipt.from_dict(
            _read_object(
                snapshot / "control/heads/00000000000000000000.json",
                "checkpoint_manifest_digest_mismatch",
            )
        ).to_dict()
    except RALValidationError as error:
        raise RALValidationError(
            "checkpoint_manifest_digest_mismatch",
            "checkpoint head-zero differs",
        ) from error
    if (
        manifest["manifest_digest"] != head["manifest_digest"]
        or manifest["registry_id"] != head["registry_id"]
    ):
        raise RALValidationError(
            "checkpoint_manifest_digest_mismatch",
            "checkpoint manifest and head differ",
        )
    return {
        "registry_id": manifest["registry_id"],
        "manifest_digest": manifest["manifest_digest"],
        "control_digest": head["control_digest"],
        "snapshot_digest": sha256_ref(_snapshot_material(snapshot)),
        "source_root_digest": sha256_ref(_source_material_from_snapshot(snapshot)),
    }


def _checkpoint_under_root(checkpoint_root: Path, storage: RegistryStorage) -> Path:
    try:
        resolved = checkpoint_root.resolve(strict=True)
        allowed = (storage.final / "checkpoints").resolve(strict=True)
        resolved.relative_to(allowed)
    except (OSError, ValueError) as error:
        raise RALValidationError(
            "checkpoint_path_escape", "checkpoint is outside the production root"
        ) from error
    if resolved.parent != allowed:
        raise RALValidationError(
            "checkpoint_path_escape", "checkpoint must be an immediate child"
        )
    return resolved


def _verify_recovery_authority(
    authority: Mapping[str, object], status: Mapping[str, object]
) -> None:
    verify_root_authority(
        authority=authority,
        plan_digest=status["plan_digest"],
        exact_root=PRODUCTION_REGISTRY_ROOT,
    )


def create_registry_checkpoint(
    root: str,
    checkpoint_id: str,
    authority: Mapping[str, object],
    time_ref: str,
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    _validate_root(root)
    _uuid4(checkpoint_id, "checkpoint_id_invalid")
    _require_time_ref(time_ref)
    selected = _selected_storage(storage)
    status = registry_root_status(storage=selected)
    _verify_recovery_authority(authority, status)
    checkpoint_root = selected.final / f"checkpoints/checkpoint-{checkpoint_id}"
    evidence_path = selected.final / "evidence/checkpoint-receipt.json"
    if checkpoint_root.exists() or evidence_path.exists():
        raise RALValidationError("checkpoint_exists", "checkpoint output exists")
    try:
        checkpoint_root.mkdir()
    except FileExistsError as error:
        raise RALValidationError(
            "checkpoint_exists", "checkpoint output exists"
        ) from error
    except OSError as error:
        raise RALValidationError(
            "checkpoint_unwritable", "checkpoint directory cannot be created"
        ) from error

    snapshot = checkpoint_root / "snapshot"
    _copy_snapshot(selected.final, snapshot)
    manifest_bytes = _manifest_bytes(snapshot)
    with (checkpoint_root / "MANIFEST.sha256").open("xb") as stream:
        stream.write(manifest_bytes)
    checkpoint = bind_document_digest(
        {
            "schema": "sedb-ral.registry-checkpoint/0.1",
            "checkpoint_id": f"checkpoint:{checkpoint_id}",
            "registry_id": status["registry_id"],
            "source_root_digest": status["tree_digest"],
            "source_control_digest": status["control_digest"],
            "source_ledger_head": None,
            "source_event_count": 0,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "snapshot_root": "snapshot",
            "created_time_ref": time_ref,
            "storage_scope": "same_volume_local",
            "not_claimed": [
                "offsite_backup",
                "volume_loss_recovery",
                "ransomware_recovery",
                "private_backup",
            ],
        },
        "checkpoint_digest",
    )
    validate_contract("registry-checkpoint.schema.json", checkpoint)
    _write_new_json(checkpoint_root / "CHECKPOINT.json", checkpoint)
    verified = verify_registry_checkpoint(checkpoint_root)
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.registry-checkpoint-receipt/0.1",
            "registry_id": status["registry_id"],
            "checkpoint_ref": f"checkpoints/checkpoint-{checkpoint_id}",
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "source_root_digest": status["tree_digest"],
            "source_event_count": 0,
            "storage_scope": "same_volume_local",
            "created_time_ref": time_ref,
            "not_claimed": ["offsite_backup", "private_backup"],
        },
        "receipt_digest",
    )
    _write_new_json(evidence_path, receipt)
    return {
        **verified,
        "checkpoint_path": str(checkpoint_root),
        "evidence_receipt_digest": receipt["receipt_digest"],
    }


def verify_registry_checkpoint(checkpoint_root: Path) -> dict[str, object]:
    root = Path(checkpoint_root)
    if not root.is_dir():
        raise RALValidationError(
            "checkpoint_unavailable", "checkpoint directory is unavailable"
        )
    directories, files = _walk(root)
    _reject_alternate_streams(files)
    _reject_private_markers(root, files)
    expected_directories = {"snapshot"} | {
        f"snapshot/{relative}" for relative in SNAPSHOT_DIRECTORIES
    }
    expected_files = {"CHECKPOINT.json", "MANIFEST.sha256"} | {
        f"snapshot/{relative}" for relative in SNAPSHOT_FILES
    }
    if {
        path.relative_to(root).as_posix() for path in directories
    } != expected_directories or {
        path.relative_to(root).as_posix() for path in files
    } != expected_files:
        raise RALValidationError(
            "checkpoint_layout_mismatch", "checkpoint layout differs"
        )
    checkpoint = _read_object(root / "CHECKPOINT.json", "checkpoint_invalid_json")
    _verify_digest(checkpoint, "checkpoint_digest", "checkpoint_digest_mismatch")
    validate_contract("registry-checkpoint.schema.json", checkpoint)
    manifest_bytes = (root / "MANIFEST.sha256").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != checkpoint["manifest_sha256"]:
        raise RALValidationError(
            "checkpoint_manifest_digest_mismatch", "checkpoint manifest differs"
        )
    facts = _verify_snapshot(root / "snapshot", manifest_bytes)
    if (
        facts["registry_id"] != checkpoint["registry_id"]
        or facts["control_digest"] != checkpoint["source_control_digest"]
        or facts["source_root_digest"] != checkpoint["source_root_digest"]
    ):
        raise RALValidationError(
            "checkpoint_manifest_digest_mismatch",
            "checkpoint metadata differs from copied bytes",
        )
    return {
        "schema": "sedb-ral.registry-checkpoint-verification/0.1",
        "verified": True,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "registry_id": checkpoint["registry_id"],
        "source_root_digest": checkpoint["source_root_digest"],
        "source_control_digest": checkpoint["source_control_digest"],
        "source_event_count": 0,
        "snapshot_digest": facts["snapshot_digest"],
        "storage_scope": "same_volume_local",
    }


def _write_recovery_evidence(
    path: Path, receipt: Mapping[str, object], rehearsal_ref: str
) -> str:
    evidence = bind_document_digest(
        {
            "schema": "sedb-ral.registry-recovery-evidence/0.1",
            "rehearsal_ref": rehearsal_ref,
            "rehearsal_receipt_digest": receipt["receipt_digest"],
            "production_digest_before": receipt["production_digest_before"],
            "production_digest_after": receipt["production_digest_after"],
            "not_claimed": ["production_mutation", "private_restore"],
        },
        "receipt_digest",
    )
    _write_new_json(path, evidence)
    return str(evidence["receipt_digest"])


def rehearse_registry_restore(
    root: str,
    checkpoint_root: Path,
    rehearsal_id: str,
    authority: Mapping[str, object],
    time_ref: str,
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    _validate_root(root)
    _uuid4(rehearsal_id, "rehearsal_id_invalid")
    _require_time_ref(time_ref)
    selected = _selected_storage(storage)
    status_before = registry_root_status(storage=selected)
    _verify_recovery_authority(authority, status_before)
    checkpoint_path = _checkpoint_under_root(Path(checkpoint_root), selected)
    checkpoint = verify_registry_checkpoint(checkpoint_path)
    target = selected.final / f"rehearsals/restore-{rehearsal_id}"
    evidence_path = selected.final / "evidence/restore-rehearsal-receipt.json"
    if target.exists() or evidence_path.exists():
        raise RALValidationError(
            "restore_rehearsal_exists", "restore rehearsal output exists"
        )
    target.mkdir()
    restored = target / "restored"
    _copy_snapshot(checkpoint_path / "snapshot", restored)
    manifest_bytes = (checkpoint_path / "MANIFEST.sha256").read_bytes()
    facts = _verify_snapshot(restored, manifest_bytes)
    status_after = registry_root_status(storage=selected)
    if status_after["tree_digest"] != status_before["tree_digest"]:
        raise RALValidationError(
            "production_mutated_during_restore", "production source bytes changed"
        )
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.registry-restore-receipt/0.1",
            "rehearsal_id": f"restore:{rehearsal_id}",
            "registry_id": checkpoint["registry_id"],
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "source_snapshot_digest": checkpoint["snapshot_digest"],
            "restored_snapshot_digest": facts["snapshot_digest"],
            "production_digest_before": status_before["tree_digest"],
            "production_digest_after": status_after["tree_digest"],
            "restored": True,
            "restored_event_count": 0,
            "created_time_ref": time_ref,
            "not_claimed": [
                "production_mutation",
                "offsite_recovery",
                "private_restore",
            ],
        },
        "receipt_digest",
    )
    validate_contract("registry-restore-receipt.schema.json", receipt)
    _write_new_json(target / "RESTORE-RECEIPT.json", receipt)
    evidence_digest = _write_recovery_evidence(
        evidence_path, receipt, f"rehearsals/restore-{rehearsal_id}"
    )
    return {
        **receipt,
        "rehearsal_path": str(target),
        "evidence_receipt_digest": evidence_digest,
    }


def rehearse_registry_rollback(
    root: str,
    checkpoint_root: Path,
    rehearsal_id: str,
    authority: Mapping[str, object],
    time_ref: str,
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    _validate_root(root)
    _uuid4(rehearsal_id, "rehearsal_id_invalid")
    _require_time_ref(time_ref)
    selected = _selected_storage(storage)
    status_before = registry_root_status(storage=selected)
    _verify_recovery_authority(authority, status_before)
    checkpoint_path = _checkpoint_under_root(Path(checkpoint_root), selected)
    checkpoint = verify_registry_checkpoint(checkpoint_path)
    target = selected.final / f"rehearsals/rollback-{rehearsal_id}"
    evidence_path = selected.final / "evidence/rollback-rehearsal-receipt.json"
    if target.exists() or evidence_path.exists():
        raise RALValidationError(
            "rollback_rehearsal_exists", "rollback rehearsal output exists"
        )
    target.mkdir()
    corrupted = target / "corrupted"
    fresh = target / "fresh"
    _copy_snapshot(checkpoint_path / "snapshot", corrupted)
    manifest_bytes = (checkpoint_path / "MANIFEST.sha256").read_bytes()
    before_corruption = sha256_ref(_snapshot_material(corrupted))
    corrupted_manifest = corrupted / "registry-manifest.json"
    corrupted_manifest.write_bytes(corrupted_manifest.read_bytes() + b" ")
    corrupted_digest = sha256_ref(_snapshot_material(corrupted))
    try:
        _verify_snapshot(corrupted, manifest_bytes)
    except RALValidationError as error:
        red_code = error.code
    else:
        raise RALValidationError(
            "rollback_red_control_failed", "corruption was not detected"
        )
    if red_code != "checkpoint_manifest_digest_mismatch":
        raise RALValidationError(
            "rollback_red_control_wrong_error", "corruption returned another error"
        )
    _copy_snapshot(checkpoint_path / "snapshot", fresh)
    fresh_facts = _verify_snapshot(fresh, manifest_bytes)
    status_after = registry_root_status(storage=selected)
    if status_after["tree_digest"] != status_before["tree_digest"]:
        raise RALValidationError(
            "production_mutated_during_rollback", "production source bytes changed"
        )
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.registry-rollback-receipt/0.1",
            "rehearsal_id": f"rollback:{rehearsal_id}",
            "registry_id": checkpoint["registry_id"],
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "before_corruption_digest": before_corruption,
            "corrupted_digest": corrupted_digest,
            "red_control_error_code": red_code,
            "fresh_restore_digest": fresh_facts["snapshot_digest"],
            "production_digest_before": status_before["tree_digest"],
            "production_digest_after": status_after["tree_digest"],
            "passed": True,
            "created_time_ref": time_ref,
            "not_claimed": [
                "production_mutation",
                "offsite_recovery",
                "volume_loss_recovery",
                "private_restore",
            ],
        },
        "receipt_digest",
    )
    validate_contract("registry-rollback-receipt.schema.json", receipt)
    _write_new_json(target / "ROLLBACK-RECEIPT.json", receipt)
    evidence_digest = _write_recovery_evidence(
        evidence_path, receipt, f"rehearsals/rollback-{rehearsal_id}"
    )
    return {
        **receipt,
        "rehearsal_path": str(target),
        "evidence_receipt_digest": evidence_digest,
    }
