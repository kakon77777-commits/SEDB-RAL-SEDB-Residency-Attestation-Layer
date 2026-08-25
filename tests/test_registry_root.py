from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_registry_root_contracts import (
    PARENT_ROOT,
    valid_acl,
    valid_authority,
    valid_plan,
)

from sedb_ral.errors import RALValidationError
from sedb_ral.registry_root import (
    RegistryStorage,
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    verify_registry_candidate,
)

EXPECTED_DIRECTORIES = {
    "ledger",
    "ledger/events",
    "ledger/anchors",
    "control",
    "control/heads",
    "checkpoints",
    "rehearsals",
    "evidence",
}
EXPECTED_FILES = {
    "registry-manifest.json",
    "control/heads/00000000000000000000.json",
    "evidence/initialization-receipt.json",
    "evidence/acl-receipt.json",
}


def ready_storage(tmp_path: Path):
    plan = valid_plan()
    authority = valid_authority(plan)
    parent_acl = valid_acl(PARENT_ROOT)
    candidate_acl = valid_acl(plan["candidate_root"])
    storage = RegistryStorage.synthetic(tmp_path)
    storage.parent.mkdir(parents=True)
    storage.candidate(plan).mkdir()
    return storage, plan, authority, parent_acl, candidate_acl


def byte_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_prepare_builds_only_the_empty_public_registry_layout(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)

    receipt = prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )

    candidate = storage.candidate(plan)
    directories = {
        path.relative_to(candidate).as_posix()
        for path in candidate.rglob("*")
        if path.is_dir()
    }
    files = {
        path.relative_to(candidate).as_posix()
        for path in candidate.rglob("*")
        if path.is_file()
    }
    assert directories == EXPECTED_DIRECTORIES
    assert files == EXPECTED_FILES
    assert list((candidate / "ledger/events").iterdir()) == []
    assert list((candidate / "ledger/anchors").iterdir()) == []
    assert receipt["schema"] == "sedb-ral.registry-initialization-result/0.1"
    assert receipt["resident_event_count"] == 0
    assert receipt["private_read_count"] == 0
    assert receipt["network_effect_count"] == 0

    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    assert verification["verified"] is True
    assert verification["ledger_event_count"] == 0
    assert verification["application_count"] == 0
    assert verification["resident_count"] == 0
    assert verification["address_count"] == 0


def test_existing_final_root_refuses_before_candidate_mutation(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    final = storage.final
    final.mkdir()
    marker = final / "owner-material.bin"
    marker.write_bytes(b"preserve exactly")

    with pytest.raises(RALValidationError) as caught:
        prepare_registry_candidate(
            plan, authority, parent_acl, candidate_acl, storage=storage
        )

    assert caught.value.code == "registry_root_exists"
    assert marker.read_bytes() == b"preserve exactly"
    assert list(storage.candidate(plan).iterdir()) == []


def test_broad_parent_acl_refuses_before_candidate_mutation(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    parent_acl["forbidden_write_sids"] = ["S-1-5-11"]
    from sedb_ral.registry_root_contracts import bind_registry_acl_fingerprint

    parent_acl = bind_registry_acl_fingerprint(
        {key: value for key, value in parent_acl.items() if key != "acl_fingerprint"}
    )

    with pytest.raises(RALValidationError) as caught:
        prepare_registry_candidate(
            plan, authority, parent_acl, candidate_acl, storage=storage
        )

    assert caught.value.code == "registry_acl_broad_write"
    assert list(storage.candidate(plan).iterdir()) == []


def test_acl_owner_must_match_the_owner_bound_into_the_plan(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    from sedb_ral.registry_root_contracts import bind_registry_acl_fingerprint

    other_owner = "S-1-5-21-9000-9001-9002-9003"
    changed_acls = []
    for observation in (parent_acl, candidate_acl):
        changed = {
            key: value for key, value in observation.items() if key != "acl_fingerprint"
        }
        changed["owner_sid"] = other_owner
        changed["required_full_control_sids"] = [
            other_owner,
            "S-1-5-18",
            "S-1-5-32-544",
        ]
        changed_acls.append(bind_registry_acl_fingerprint(changed))

    with pytest.raises(RALValidationError) as caught:
        prepare_registry_candidate(
            plan,
            authority,
            changed_acls[0],
            changed_acls[1],
            storage=storage,
        )

    assert caught.value.code == "registry_acl_owner_mismatch"
    assert list(storage.candidate(plan).iterdir()) == []


def test_acl_volume_identity_must_match_the_plan(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    from sedb_ral.registry_root_contracts import bind_registry_acl_fingerprint

    changed_acls = []
    for observation in (parent_acl, candidate_acl):
        changed = {
            key: value for key, value in observation.items() if key != "acl_fingerprint"
        }
        changed["volume_identity"] = "volume:other"
        changed_acls.append(bind_registry_acl_fingerprint(changed))

    with pytest.raises(RALValidationError) as caught:
        prepare_registry_candidate(
            plan,
            authority,
            changed_acls[0],
            changed_acls[1],
            storage=storage,
        )

    assert caught.value.code == "volume_identity_mismatch"
    assert list(storage.candidate(plan).iterdir()) == []


@pytest.mark.parametrize(
    ("relative_path", "payload", "code"),
    [
        ("registry-manifest.json", b"x", "registry_manifest_invalid_json"),
        (
            "control/heads/00000000000000000000.json",
            b"{}",
            "external_head_mismatch",
        ),
        ("ledger/events/00000000000000000001.json", b"{}", "nonempty_ledger"),
        ("evidence/AI_HOME-export.txt", b"private bytes", "private_marker_detected"),
    ],
)
def test_candidate_mutation_or_forbidden_material_turns_verification_red(
    tmp_path, relative_path, payload, code
):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    target = storage.candidate(plan) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    with pytest.raises(RALValidationError) as caught:
        verify_registry_candidate(
            plan, authority, parent_acl, candidate_acl, storage=storage
        )

    assert caught.value.code == code


def test_same_inputs_produce_identical_candidate_bytes(tmp_path):
    left = ready_storage(tmp_path / "left")
    right = ready_storage(tmp_path / "right")

    for storage, plan, authority, parent_acl, candidate_acl in (left, right):
        prepare_registry_candidate(
            plan, authority, parent_acl, candidate_acl, storage=storage
        )

    assert byte_map(left[0].candidate(left[1])) == byte_map(
        right[0].candidate(right[1])
    )


def test_verified_candidate_publishes_by_no_replace_rename(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    candidate_bytes = byte_map(storage.candidate(plan))

    receipt = publish_registry_candidate(plan, verification, storage=storage)

    assert not storage.candidate(plan).exists()
    assert storage.final.is_dir()
    assert byte_map(storage.final) == candidate_bytes
    assert receipt["published"] is True
    status = registry_root_status(storage=storage)
    assert status["verified"] is True
    assert status["ledger_event_count"] == 0

    with pytest.raises(RALValidationError) as caught:
        publish_registry_candidate(plan, verification, storage=storage)
    assert caught.value.code == "registry_root_exists"
    assert byte_map(storage.final) == candidate_bytes


def test_stale_verification_refuses_publication(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    manifest = storage.candidate(plan) / "registry-manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")

    with pytest.raises(RALValidationError) as caught:
        publish_registry_candidate(plan, verification, storage=storage)

    assert caught.value.code == "candidate_tree_digest_mismatch"
    assert not storage.final.exists()


def test_tampered_verification_receipt_refuses_publication(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification["private_read_count"] = 1

    with pytest.raises(RALValidationError) as caught:
        publish_registry_candidate(plan, verification, storage=storage)

    assert caught.value.code == "candidate_verification_digest_mismatch"
    assert not storage.final.exists()


def test_reparse_point_inside_candidate_is_refused(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    link = storage.candidate(plan) / "evidence" / "escape-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")

    with pytest.raises(RALValidationError) as caught:
        verify_registry_candidate(
            plan, authority, parent_acl, candidate_acl, storage=storage
        )
    assert caught.value.code == "registry_root_reparse_point"


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate streams are Windows-only")
def test_alternate_data_stream_inside_candidate_is_refused(tmp_path):
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    manifest = storage.candidate(plan) / "registry-manifest.json"
    try:
        Path(str(manifest) + ":private").write_bytes(b"hidden")
    except OSError as error:
        pytest.skip(f"alternate streams unavailable: {error}")

    with pytest.raises(RALValidationError) as caught:
        verify_registry_candidate(
            plan, authority, parent_acl, candidate_acl, storage=storage
        )
    assert caught.value.code == "alternate_data_stream_detected"
