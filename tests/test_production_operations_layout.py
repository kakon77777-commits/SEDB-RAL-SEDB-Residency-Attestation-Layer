from __future__ import annotations

from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.production_operations_contracts import (
    plan_production_operations_extension,
)
from sedb_ral.production_operations_layout import (
    prepare_production_operations_candidate,
    publish_production_operations_candidate,
    registry_generation_digest,
    verify_production_operations_candidate,
    write_activation_receipt,
)
from sedb_ral.registry_root import (
    RegistryStorage,
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    registry_source_digest,
    verify_registry_candidate,
)
from sedb_ral.registry_root_contracts import bind_document_digest
from production_operations_helpers import (
    CANDIDATE_ID,
    GENERATION,
    TIME_REF,
    authority_value,
    digest,
    dormant_policy,
    manifest_value,
)
from test_registry_root import ready_storage
from test_registry_root_contracts import valid_acl


@pytest.fixture
def published_storage(tmp_path: Path) -> RegistryStorage:
    storage, plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    publish_registry_candidate(plan, verification, storage=storage)
    return storage


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def install_extension(storage: RegistryStorage, *, remove: str | None = None):
    status = registry_root_status(storage=storage)
    policy = dormant_policy.__wrapped__()
    plan = plan_production_operations_extension(
        registry_status=status,
        candidate_id=CANDIDATE_ID,
        operations_generation=GENERATION,
        policy_digest=policy["policy_digest"],
        source_commit="2470be770962556998925a739c3d1099dc830786",
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity="volume:sha256:" + "1" * 64,
        expected_owner_sid="S-1-5-21-1000",
        acl_fingerprint=digest("2"),
        pre_checkpoint_digest=digest("3"),
        time_ref=TIME_REF,
    )
    authority = authority_value(plan["plan_digest"])
    manifest = manifest_value(plan, policy["policy_digest"])
    commit = bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-activation-commit/0.1",
            "candidate_id": CANDIDATE_ID,
            "plan_digest": plan["plan_digest"],
            "authority_digest": authority["authority_digest"],
            "manifest_digest": manifest["manifest_digest"],
            "policy_digest": policy["policy_digest"],
            "pre_checkpoint_digest": plan["pre_checkpoint_digest"],
            "committed_time_ref": TIME_REF,
            "not_claimed": [
                "published",
                "ledger_append",
                "resident_registration",
                "private_access",
            ],
        },
        "commit_digest",
    )
    index = bind_document_digest(
        {
            "schema": "sedb-ral.registry-extension-index/0.1",
            "index_sequence": 0,
            "extension_kind": "registrar-operations",
            "extension_version": "v1",
            "extension_ref": "extensions/registrar-operations/v1",
            "extension_manifest_digest": manifest["manifest_digest"],
            "activation_commit_digest": commit["commit_digest"],
            "operations_generation": GENERATION,
            "previous_index_digest": None,
            "source_commit": plan["source_commit"],
            "source_package_version": "0.5.0b1",
            "pre_checkpoint_digest": plan["pre_checkpoint_digest"],
            "recorded_time_ref": TIME_REF,
            "not_claimed": [
                "ledger_head",
                "resident_registration",
                "authority_grant",
            ],
        },
        "index_digest",
    )
    extension = storage.final / "extensions/registrar-operations/v1"
    for relative in (
        "policies",
        "active-policy",
        "inbox",
        "requests",
        "receipts",
        "audit",
        "leases",
        "projections/public",
        "staging",
    ):
        (extension / relative).mkdir(parents=True, exist_ok=True)
    activation = bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-policy-activation/0.1",
            "control_sequence": 0,
            "operations_generation": GENERATION,
            "policy_digest": policy["policy_digest"],
            "previous_control_digest": None,
            "activated_time_ref": TIME_REF,
            "execution_enabled": False,
            "not_claimed": ["registrar_authority", "resident_registration"],
        },
        "control_digest",
    )
    write_json(storage.final / "extensions/index/00000000000000000000.json", index)
    write_json(extension / "EXTENSION-MANIFEST.json", manifest)
    write_json(extension / "ACTIVATION-COMMIT.json", commit)
    write_json(extension / "policies/policy-production-dormant-v1.json", policy)
    write_json(extension / "active-policy/00000000000000000000.json", activation)
    if remove is not None:
        (storage.final / remove).unlink()
    return plan, index


def test_absent_extension_preserves_exact_base_digest(published_storage):
    before = registry_root_status(storage=published_storage)

    assert before["extensions_status"] == "absent"
    assert before["extension_index_digest"] is None
    assert before["operations_generation"] is None
    assert before["activation_receipt_status"] == "absent"
    assert before["tree_digest"] == registry_source_digest(published_storage.final)
    assert before["registry_generation_digest"] == registry_generation_digest(
        before, None
    )


def test_complete_extension_without_receipt_is_dormant_unreceipted(
    published_storage,
):
    _, index = install_extension(published_storage)

    status = registry_root_status(storage=published_storage)

    assert status["extensions_status"] == "active_dormant_unreceipted"
    assert status["activation_receipt_status"] == "missing"
    assert status["extension_index_digest"] == index["index_digest"]
    assert status["operations_generation"] == GENERATION
    assert status["resident_count"] == 0


def write_fixture_activation_receipt(storage, plan, index, generation_digest):
    receipt = bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-activation-receipt/0.1",
            "candidate_id": CANDIDATE_ID,
            "registry_id": plan["registry_id"],
            "extension_index_digest": index["index_digest"],
            "registry_generation_digest": generation_digest,
            "observed_final_ref": "extensions/registrar-operations/v1",
            "observed_time_ref": TIME_REF,
            "not_claimed": [
                "ledger_append",
                "resident_registration",
                "private_access",
            ],
        },
        "receipt_digest",
    )
    write_json(
        storage.final
        / f"evidence/operations-extension-activation-{CANDIDATE_ID}.json",
        receipt,
    )


def test_exact_post_move_receipt_activates_dormant_status(published_storage):
    plan, index = install_extension(published_storage)
    unreceipted = registry_root_status(storage=published_storage)
    write_fixture_activation_receipt(
        published_storage,
        plan,
        index,
        unreceipted["registry_generation_digest"],
    )

    status = registry_root_status(storage=published_storage)

    assert status["extensions_status"] == "active_dormant"
    assert status["activation_receipt_status"] == "verified"


def test_unknown_top_level_extension_like_directory_is_not_accepted(
    published_storage,
):
    (published_storage.final / "extensions-bogus").mkdir()

    with pytest.raises(RALValidationError, match="registry_layout_mismatch"):
        registry_root_status(storage=published_storage)


@pytest.mark.parametrize(
    "missing",
    [
        "extensions/index/00000000000000000000.json",
        "extensions/registrar-operations/v1/EXTENSION-MANIFEST.json",
        "extensions/registrar-operations/v1/ACTIVATION-COMMIT.json",
        "extensions/registrar-operations/v1/policies/policy-production-dormant-v1.json",
        "extensions/registrar-operations/v1/active-policy/00000000000000000000.json",
    ],
)
def test_present_incomplete_extension_fails_closed(published_storage, missing):
    install_extension(published_storage, remove=missing)

    with pytest.raises(RALValidationError, match="production_operations_extension_layout_mismatch"):
        registry_root_status(storage=published_storage)


def candidate_inputs(storage):
    status = registry_root_status(storage=storage)
    policy = dormant_policy.__wrapped__()
    candidate_root = rf"D:\AI_RESIDENCE\REGISTRY\.SEDB-RAL.operations-{CANDIDATE_ID}"
    acl = valid_acl(candidate_root)
    plan = plan_production_operations_extension(
        registry_status=status,
        candidate_id=CANDIDATE_ID,
        operations_generation=GENERATION,
        policy_digest=policy["policy_digest"],
        source_commit="2470be770962556998925a739c3d1099dc830786",
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity=acl["volume_identity"],
        expected_owner_sid=acl["owner_sid"],
        acl_fingerprint=acl["acl_fingerprint"],
        pre_checkpoint_digest=digest("3"),
        time_ref=TIME_REF,
    )
    return plan, authority_value(plan["plan_digest"]), acl, policy


def test_atomic_publish_moves_only_complete_extensions_tree(published_storage):
    plan, authority, acl, policy = candidate_inputs(published_storage)
    candidate = published_storage.parent / plan["candidate_name"]
    candidate.mkdir()
    prepared = prepare_production_operations_candidate(
        plan, authority, acl, policy, storage=published_storage
    )
    verified = verify_production_operations_candidate(
        plan, prepared, storage=published_storage
    )

    result = publish_production_operations_candidate(
        plan, verified, storage=published_storage
    )

    assert result["published"] is True
    assert (published_storage.final / "extensions").is_dir()
    assert not (candidate / "extensions").exists()
    assert registry_root_status(storage=published_storage)["extensions_status"] == "active_dormant_unreceipted"


def test_candidate_tamper_after_verification_refuses_publication(published_storage):
    plan, authority, acl, policy = candidate_inputs(published_storage)
    candidate = published_storage.parent / plan["candidate_name"]
    candidate.mkdir()
    prepared = prepare_production_operations_candidate(
        plan, authority, acl, policy, storage=published_storage
    )
    verified = verify_production_operations_candidate(
        plan, prepared, storage=published_storage
    )
    (candidate / "extensions/registrar-operations/v1/inbox/tampered.json").write_text("{}")

    with pytest.raises(RALValidationError, match="production_operations_candidate_tree_digest_mismatch"):
        publish_production_operations_candidate(
            plan, verified, storage=published_storage
        )
    assert not (published_storage.final / "extensions").exists()


def test_existing_destination_refuses_without_replacement(published_storage):
    install_extension(published_storage)
    before = (published_storage.final / "extensions/index/00000000000000000000.json").read_bytes()
    plan, authority, acl, policy = candidate_inputs(published_storage)
    candidate = published_storage.parent / plan["candidate_name"]
    candidate.mkdir()

    with pytest.raises(RALValidationError, match="production_operations_extension_exists"):
        prepare_production_operations_candidate(
            plan, authority, acl, policy, storage=published_storage
        )
    assert (published_storage.final / "extensions/index/00000000000000000000.json").read_bytes() == before


def test_post_move_receipt_is_create_only_and_activates_status(published_storage):
    plan, authority, acl, policy = candidate_inputs(published_storage)
    candidate = published_storage.parent / plan["candidate_name"]
    candidate.mkdir()
    prepared = prepare_production_operations_candidate(
        plan, authority, acl, policy, storage=published_storage
    )
    verified = verify_production_operations_candidate(
        plan, prepared, storage=published_storage
    )
    publish_production_operations_candidate(plan, verified, storage=published_storage)
    index = _read_object(
        published_storage.final / "extensions/index/00000000000000000000.json"
    )

    receipt = write_activation_receipt(
        root=published_storage.final,
        plan=plan,
        index=index,
        observed_time_ref=TIME_REF,
    )

    assert receipt["candidate_id"] == CANDIDATE_ID
    assert registry_root_status(storage=published_storage)["extensions_status"] == "active_dormant"
    with pytest.raises(RALValidationError):
        write_activation_receipt(
            root=published_storage.final,
            plan=plan,
            index=index,
            observed_time_ref=TIME_REF,
        )


def _read_object(path: Path) -> dict[str, object]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
