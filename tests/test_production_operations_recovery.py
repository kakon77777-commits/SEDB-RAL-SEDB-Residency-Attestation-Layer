from __future__ import annotations

import json
from pathlib import Path

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.production_operations_layout import (
    prepare_production_operations_candidate,
    publish_production_operations_candidate,
    verify_production_operations_candidate,
    write_activation_receipt,
)
from sedb_ral.production_operations_recovery import (
    create_versioned_registry_checkpoint,
    rehearse_versioned_registry_restore,
    rehearse_versioned_registry_rollback,
    verify_versioned_registry_checkpoint,
)
from sedb_ral.registry_root import registry_root_status
from production_operations_helpers import TIME_REF
from test_production_operations_layout import (
    candidate_inputs,
    published_storage,
)
from test_registry_root_contracts import valid_authority, valid_plan


PRE_ID = "31cbfa29-4b0c-4b96-aef0-42e653b3f482"
POST_ID = "a905087e-1a4f-43d3-95bc-32e84e271234"
RESTORE_ID = "ce8cbf4b-4e2d-41c7-a513-d6edb67e3447"
ROLLBACK_ID = "d26294ef-55c6-4fd4-9d43-2ecf7ae7504f"
PRODUCTION_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"


def recovery_authority():
    return valid_authority(valid_plan())


def activate_extension(storage):
    plan, authority, acl, policy = candidate_inputs(storage)
    candidate = storage.parent / plan["candidate_name"]
    candidate.mkdir()
    prepared = prepare_production_operations_candidate(
        plan, authority, acl, policy, storage=storage
    )
    verified = verify_production_operations_candidate(plan, prepared, storage=storage)
    publish_production_operations_candidate(plan, verified, storage=storage)
    index = json.loads(
        (storage.final / "extensions/index/00000000000000000000.json").read_text(
            encoding="utf-8"
        )
    )
    write_activation_receipt(
        root=storage.final,
        plan=plan,
        index=index,
        observed_time_ref=TIME_REF,
    )
    assert registry_root_status(storage=storage)["extensions_status"] == "active_dormant"


def test_pre_and_post_extension_checkpoints_coexist(published_storage):
    authority = recovery_authority()
    pre = create_versioned_registry_checkpoint(
        root=PRODUCTION_ROOT,
        checkpoint_id=PRE_ID,
        phase="pre_activation",
        authority=authority,
        time_ref="time:host-wall-clock-unverified:2026-08-26T00:01:00+08:00",
        storage=published_storage,
    )
    activate_extension(published_storage)
    post = create_versioned_registry_checkpoint(
        root=PRODUCTION_ROOT,
        checkpoint_id=POST_ID,
        phase="post_activation",
        authority=authority,
        time_ref="time:host-wall-clock-unverified:2026-08-26T00:02:00+08:00",
        storage=published_storage,
    )

    assert pre["checkpoint_digest"] != post["checkpoint_digest"]
    receipts = list((published_storage.final / "evidence/checkpoints").glob("*.json"))
    assert len(receipts) == 2
    assert not (published_storage.final / "evidence/checkpoint-receipt.json").exists()
    assert verify_versioned_registry_checkpoint(
        published_storage.final / f"checkpoints/checkpoint-{POST_ID}"
    )["registry_generation_digest"] == registry_root_status(
        storage=published_storage
    )["registry_generation_digest"]


def test_extension_corruption_in_checkpoint_is_detected(published_storage):
    activate_extension(published_storage)
    result = create_versioned_registry_checkpoint(
        root=PRODUCTION_ROOT,
        checkpoint_id=POST_ID,
        phase="post_activation",
        authority=recovery_authority(),
        time_ref=TIME_REF,
        storage=published_storage,
    )
    checkpoint = Path(result["checkpoint_path"])
    target = checkpoint / "snapshot/extensions/registrar-operations/v1/EXTENSION-MANIFEST.json"
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(RALValidationError, match="versioned_checkpoint_manifest_mismatch"):
        verify_versioned_registry_checkpoint(checkpoint)


def test_restore_and_rollback_are_isolated_and_leave_live_generation_unchanged(
    published_storage,
):
    activate_extension(published_storage)
    checkpoint = create_versioned_registry_checkpoint(
        root=PRODUCTION_ROOT,
        checkpoint_id=POST_ID,
        phase="post_activation",
        authority=recovery_authority(),
        time_ref=TIME_REF,
        storage=published_storage,
    )
    before = registry_root_status(storage=published_storage)["registry_generation_digest"]

    restore = rehearse_versioned_registry_restore(
        root=PRODUCTION_ROOT,
        checkpoint_root=Path(checkpoint["checkpoint_path"]),
        rehearsal_id=RESTORE_ID,
        authority=recovery_authority(),
        time_ref=TIME_REF,
        storage=published_storage,
    )
    rollback = rehearse_versioned_registry_rollback(
        root=PRODUCTION_ROOT,
        checkpoint_root=Path(checkpoint["checkpoint_path"]),
        rehearsal_id=ROLLBACK_ID,
        authority=recovery_authority(),
        time_ref=TIME_REF,
        storage=published_storage,
    )

    assert restore["restored"] is True
    assert rollback["passed"] is True
    assert rollback["red_control_error_code"] == "versioned_checkpoint_manifest_mismatch"
    assert registry_root_status(storage=published_storage)["registry_generation_digest"] == before


def test_unknown_versioned_evidence_file_is_not_allowlisted(published_storage):
    target = published_storage.final / "evidence/checkpoints/not-a-receipt.bin"
    target.parent.mkdir()
    target.write_bytes(b"opaque")

    with pytest.raises(RALValidationError, match="registry_layout_mismatch"):
        registry_root_status(storage=published_storage)
