from __future__ import annotations

from pathlib import Path

import pytest
from test_registry_root import byte_map, ready_storage

from sedb_ral.errors import RALValidationError
from sedb_ral.registry_recovery import (
    create_registry_checkpoint,
    rehearse_registry_restore,
    rehearse_registry_rollback,
    verify_registry_checkpoint,
)
from sedb_ral.registry_root import (
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    verify_registry_candidate,
)

CHECKPOINT_ID = "2b56ad9c-d2d8-4240-8c79-0d84533a48f8"
RESTORE_ID = "5fd90e58-a64c-4a73-805b-2089b1f18db4"
ROLLBACK_ID = "7b5a8d1c-714c-4a22-8d2b-61002f4d9b98"


def published_storage(tmp_path: Path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    publish_registry_candidate(plan, verification, storage=storage)
    return storage, plan, authority


def test_checkpoint_is_create_only_value_copy_with_exact_manifest(tmp_path):
    storage, _, authority = published_storage(tmp_path)
    before = registry_root_status(storage=storage)["tree_digest"]

    result = create_registry_checkpoint(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_id=CHECKPOINT_ID,
        authority=authority,
        time_ref="time:test:checkpoint",
        storage=storage,
    )

    checkpoint = storage.final / f"checkpoints/checkpoint-{CHECKPOINT_ID}"
    assert checkpoint.is_dir()
    assert {path.name for path in checkpoint.iterdir()} == {
        "CHECKPOINT.json",
        "MANIFEST.sha256",
        "snapshot",
    }
    assert not any(path.is_symlink() for path in checkpoint.rglob("*"))
    verified = verify_registry_checkpoint(checkpoint)
    assert verified["verified"] is True
    assert verified["checkpoint_digest"] == result["checkpoint_digest"]
    assert verified["source_event_count"] == 0
    assert verified["storage_scope"] == "same_volume_local"
    assert registry_root_status(storage=storage)["tree_digest"] == before
    assert (storage.final / "evidence/checkpoint-receipt.json").is_file()

    with pytest.raises(RALValidationError) as caught:
        create_registry_checkpoint(
            root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
            checkpoint_id=CHECKPOINT_ID,
            authority=authority,
            time_ref="time:test:checkpoint",
            storage=storage,
        )
    assert caught.value.code == "checkpoint_exists"


def test_checkpoint_byte_mutation_turns_manifest_verification_red(tmp_path):
    storage, _, authority = published_storage(tmp_path)
    result = create_registry_checkpoint(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_id=CHECKPOINT_ID,
        authority=authority,
        time_ref="time:test:checkpoint",
        storage=storage,
    )
    checkpoint = Path(result["checkpoint_path"])
    manifest = checkpoint / "snapshot/registry-manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")

    with pytest.raises(RALValidationError) as caught:
        verify_registry_checkpoint(checkpoint)

    assert caught.value.code == "checkpoint_manifest_digest_mismatch"


def test_isolated_restore_is_byte_identical_and_leaves_production_unchanged(
    tmp_path,
):
    storage, _, authority = published_storage(tmp_path)
    checkpoint_result = create_registry_checkpoint(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_id=CHECKPOINT_ID,
        authority=authority,
        time_ref="time:test:checkpoint",
        storage=storage,
    )
    production_before = registry_root_status(storage=storage)["tree_digest"]
    checkpoint = Path(checkpoint_result["checkpoint_path"])

    result = rehearse_registry_restore(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_root=checkpoint,
        rehearsal_id=RESTORE_ID,
        authority=authority,
        time_ref="time:test:restore",
        storage=storage,
    )

    rehearsal = storage.final / f"rehearsals/restore-{RESTORE_ID}"
    restored = rehearsal / "restored"
    assert result["restored"] is True
    assert byte_map(restored) == byte_map(checkpoint / "snapshot")
    assert (rehearsal / "RESTORE-RECEIPT.json").is_file()
    assert (storage.final / "evidence/restore-rehearsal-receipt.json").is_file()
    assert registry_root_status(storage=storage)["tree_digest"] == production_before


@pytest.mark.parametrize("rehearsal_id", ["../escape", "not-a-uuid"])
def test_restore_target_escape_is_refused_before_write(tmp_path, rehearsal_id):
    storage, _, authority = published_storage(tmp_path)
    checkpoint_result = create_registry_checkpoint(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_id=CHECKPOINT_ID,
        authority=authority,
        time_ref="time:test:checkpoint",
        storage=storage,
    )
    rehearsals_before = byte_map(storage.final / "rehearsals")

    with pytest.raises(RALValidationError) as caught:
        rehearse_registry_restore(
            root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
            checkpoint_root=Path(checkpoint_result["checkpoint_path"]),
            rehearsal_id=rehearsal_id,
            authority=authority,
            time_ref="time:test:restore",
            storage=storage,
        )

    assert caught.value.code == "rehearsal_id_invalid"
    assert byte_map(storage.final / "rehearsals") == rehearsals_before


def test_checkpoint_outside_the_registry_is_refused(tmp_path):
    storage, _, authority = published_storage(tmp_path)
    outside = tmp_path / "outside-checkpoint"
    outside.mkdir()

    with pytest.raises(RALValidationError) as caught:
        rehearse_registry_restore(
            root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
            checkpoint_root=outside,
            rehearsal_id=RESTORE_ID,
            authority=authority,
            time_ref="time:test:restore",
            storage=storage,
        )

    assert caught.value.code == "checkpoint_path_escape"


def test_rollback_detects_corruption_then_freshly_restores_exact_bytes(tmp_path):
    storage, _, authority = published_storage(tmp_path)
    checkpoint_result = create_registry_checkpoint(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_id=CHECKPOINT_ID,
        authority=authority,
        time_ref="time:test:checkpoint",
        storage=storage,
    )
    checkpoint = Path(checkpoint_result["checkpoint_path"])
    production_before = registry_root_status(storage=storage)["tree_digest"]

    result = rehearse_registry_rollback(
        root=r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
        checkpoint_root=checkpoint,
        rehearsal_id=ROLLBACK_ID,
        authority=authority,
        time_ref="time:test:rollback",
        storage=storage,
    )

    rehearsal = storage.final / f"rehearsals/rollback-{ROLLBACK_ID}"
    assert result["passed"] is True
    assert result["red_control_error_code"] == ("checkpoint_manifest_digest_mismatch")
    assert byte_map(rehearsal / "fresh") == byte_map(checkpoint / "snapshot")
    assert byte_map(rehearsal / "corrupted") != byte_map(checkpoint / "snapshot")
    assert (rehearsal / "ROLLBACK-RECEIPT.json").is_file()
    assert (storage.final / "evidence/rollback-rehearsal-receipt.json").is_file()
    assert registry_root_status(storage=storage)["tree_digest"] == production_before
