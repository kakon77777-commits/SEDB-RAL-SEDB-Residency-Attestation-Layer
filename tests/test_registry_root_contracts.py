from __future__ import annotations

import copy
from uuid import UUID

import pytest

from sedb_ral.canonical import sha256_ref
from sedb_ral.contracts import load_schema, validate_contract
from sedb_ral.errors import RALValidationError
from sedb_ral.registry_root_contracts import (
    APPROVED_ROOT_SCOPES,
    PRODUCTION_REGISTRY_ROOT,
    ProductionRegistryManifest,
    RegistryAclObservation,
    RegistryHeadReceipt,
    RegistryRootAuthority,
    RegistryRootPlan,
    bind_document_digest,
    plan_registry_root,
    verify_registry_acl,
    verify_root_authority,
)

FINAL_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
PARENT_ROOT = r"D:\AI_RESIDENCE\REGISTRY"
CANDIDATE_ID = "6f5121df-a649-49f3-a3f8-f1ef7df6f3af"
OWNER_SID = "S-1-5-21-1000-1001-1002-1003"
TIME_REF = "time:host-wall-clock-unverified:2026-08-25T12:00:00+08:00"


def valid_plan() -> dict[str, object]:
    return plan_registry_root(
        final_root=FINAL_ROOT,
        candidate_id=CANDIDATE_ID,
        source_commit="a" * 40,
        source_package_version="0.4.0",
        time_ref=TIME_REF,
        filesystem="NTFS",
        volume_identity="volume:test-d",
        expected_owner_sid=OWNER_SID,
    )


def valid_authority(plan: dict[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "sedb-ral.registry-root-authority/0.1",
        "authority_id": "authority:4e928ea1-0827-40d1-b6bf-47dc9cba1708",
        "operation_plan_digest": plan["plan_digest"],
        "exact_root": FINAL_ROOT,
        "scopes": list(APPROVED_ROOT_SCOPES),
        "status": "active",
        "issued_time_ref": TIME_REF,
        "authorization_basis": "direct_user_instruction",
        "expires_after_plan_completion": True,
        "not_claimed": [
            "resident_identity",
            "resident_registration",
            "private_access",
            "delete_authority",
        ],
    }
    return bind_document_digest(value, "authority_digest")


def valid_acl(root: str) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "sedb-ral.registry-acl-observation/0.1",
        "observed_root": root,
        "owner_sid": OWNER_SID,
        "filesystem": "NTFS",
        "volume_identity": "volume:test-d",
        "inheritance_protected": True,
        "reparse_point": False,
        "required_full_control_sids": [
            OWNER_SID,
            "S-1-5-18",
            "S-1-5-32-544",
        ],
        "forbidden_write_sids": [],
        "sddl_sha256": "0" * 64,
        "observed_time_ref": TIME_REF,
        "not_claimed": [
            "offsite_backup",
            "private_confidentiality",
            "multi_host_security",
        ],
    }
    return bind_document_digest(value, "acl_fingerprint")


def test_root_plan_is_deterministic_and_binds_exact_candidate():
    first = valid_plan()
    second = valid_plan()

    assert first == second
    assert first["schema"] == "sedb-ral.registry-root-plan/0.1"
    assert first["operation"] == "registry.root.initialize"
    assert first["final_root"] == FINAL_ROOT
    assert first["registry_parent"] == PARENT_ROOT
    assert first["candidate_name"] == f".SEDB-RAL.init-{CANDIDATE_ID}"
    assert first["candidate_root"] == (PARENT_ROOT + rf"\.SEDB-RAL.init-{CANDIDATE_ID}")
    assert first["expected_owner_sid"] == OWNER_SID
    UUID(CANDIDATE_ID)
    material = dict(first)
    digest = material.pop("plan_digest")
    assert digest == sha256_ref(material)
    assert RegistryRootPlan.from_dict(first).to_dict() == first


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"final_root": r"D:\AI_RESIDENCE\AI_HOME"}, "root_target_mismatch"),
        ({"final_root": r"\\host\share\SEDB-RAL"}, "root_target_mismatch"),
        ({"candidate_id": "not-a-uuid"}, "candidate_id_invalid"),
        ({"filesystem": "ReFS"}, "filesystem_mismatch"),
        ({"expected_owner_sid": "not-a-sid"}, "owner_sid_invalid"),
    ],
)
def test_root_plan_rejects_target_or_volume_drift(override, code):
    arguments = {
        "final_root": FINAL_ROOT,
        "candidate_id": CANDIDATE_ID,
        "source_commit": "a" * 40,
        "source_package_version": "0.4.0",
        "time_ref": TIME_REF,
        "filesystem": "NTFS",
        "volume_identity": "volume:test-d",
        "expected_owner_sid": OWNER_SID,
    }
    arguments.update(override)

    with pytest.raises(RALValidationError) as caught:
        plan_registry_root(**arguments)

    assert caught.value.code == code


def test_authority_accepts_only_the_five_approved_root_scopes():
    plan = valid_plan()
    authority = valid_authority(plan)

    verify_root_authority(
        authority=authority,
        plan_digest=plan["plan_digest"],
        exact_root=FINAL_ROOT,
    )
    assert RegistryRootAuthority.from_dict(authority).to_dict() == authority

    expanded = copy.deepcopy(authority)
    expanded["scopes"].append("registry.resident.register")
    expanded = bind_document_digest(
        {key: value for key, value in expanded.items() if key != "authority_digest"},
        "authority_digest",
    )
    with pytest.raises(RALValidationError) as caught:
        verify_root_authority(
            authority=expanded,
            plan_digest=plan["plan_digest"],
            exact_root=FINAL_ROOT,
        )
    assert caught.value.code == "root_authority_scope_mismatch"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"operation_plan_digest": "sha256:wrong"}, "root_authority_plan_mismatch"),
        ({"exact_root": PARENT_ROOT}, "root_authority_target_mismatch"),
        ({"status": "revoked"}, "root_authority_inactive"),
    ],
)
def test_authority_is_bound_to_active_exact_plan(change, code):
    plan = valid_plan()
    authority = valid_authority(plan)
    authority.update(change)
    authority = bind_document_digest(
        {key: value for key, value in authority.items() if key != "authority_digest"},
        "authority_digest",
    )

    with pytest.raises(RALValidationError) as caught:
        verify_root_authority(
            authority=authority,
            plan_digest=plan["plan_digest"],
            exact_root=FINAL_ROOT,
        )

    assert caught.value.code == code


def test_parent_and_candidate_acl_require_protected_reviewed_sids():
    parent = valid_acl(PARENT_ROOT)
    candidate = valid_acl(valid_plan()["candidate_root"])

    verify_registry_acl(
        observation=parent,
        expected_root=PARENT_ROOT,
        expected_owner_sid=OWNER_SID,
    )
    assert RegistryAclObservation.from_dict(parent).to_dict() == parent
    verify_registry_acl(
        observation=candidate,
        expected_root=valid_plan()["candidate_root"],
        expected_owner_sid=OWNER_SID,
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"inheritance_protected": False}, "registry_acl_inheritance_enabled"),
        ({"reparse_point": True}, "registry_root_reparse_point"),
        (
            {"required_full_control_sids": [OWNER_SID]},
            "registry_acl_required_access_missing",
        ),
        ({"forbidden_write_sids": ["S-1-5-11"]}, "registry_acl_broad_write"),
        ({"filesystem": "ReFS"}, "filesystem_mismatch"),
    ],
)
def test_acl_rejects_broad_or_incomplete_access(change, code):
    value = valid_acl(PARENT_ROOT)
    value.update(change)
    value = bind_document_digest(
        {key: item for key, item in value.items() if key != "acl_fingerprint"},
        "acl_fingerprint",
    )

    with pytest.raises(RALValidationError) as caught:
        verify_registry_acl(
            observation=value,
            expected_root=PARENT_ROOT,
            expected_owner_sid=OWNER_SID,
        )

    assert caught.value.code == code


SCHEMA_NAMES = (
    "registry-root-plan.schema.json",
    "registry-root-authority.schema.json",
    "registry-acl-observation.schema.json",
    "production-registry-manifest.schema.json",
    "registry-head-receipt.schema.json",
    "registry-checkpoint.schema.json",
    "registry-restore-receipt.schema.json",
    "registry-rollback-receipt.schema.json",
)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_registry_root_schema_assets_are_strict(name):
    schema = load_schema(name)
    assert schema["$id"].startswith("https://evemisslab.com/schemas/sedb-ral/")
    assert schema["additionalProperties"] is False


def test_plan_schema_accepts_core_output_and_rejects_unknown_fields():
    value = valid_plan()
    validate_contract("registry-root-plan.schema.json", value)
    value["resident_name"] = "forbidden"
    with pytest.raises(RALValidationError) as caught:
        validate_contract("registry-root-plan.schema.json", value)
    assert caught.value.code == "schema_invalid"


def test_manifest_and_head_value_objects_verify_bound_digests():
    manifest_material: dict[str, object] = {
        "schema": "sedb-ral.production-registry-manifest/0.1",
        "registry_id": "registry:31e5ee61-2909-4f0d-bdaf-d0aa2f77ed92",
        "root_kind": "public_registry",
        "canonical_ledger_ref": "ledger",
        "control_heads_ref": "control/heads",
        "checkpoints_ref": "checkpoints",
        "rehearsals_ref": "rehearsals",
        "evidence_ref": "evidence",
        "source_package_name": "sedb-ral",
        "source_package_version": "0.4.0",
        "source_commit": "a" * 40,
        "canonicalization_version": "sedb-ral-json-nfc-codepoint-v1",
        "chain_version": "sedb-ral-ledger-chain-v1",
        "filesystem": "NTFS",
        "volume_identity": "volume:test-d",
        "acl_fingerprint": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "1" * 64,
        "initialized_time_ref": TIME_REF,
        "initial_control_ref": "control/heads/00000000000000000000.json",
        "not_claimed": [
            "resident_registration",
            "private_access",
            "offsite_backup",
        ],
    }
    manifest = bind_document_digest(manifest_material, "manifest_digest")
    parsed_manifest = ProductionRegistryManifest.from_dict(manifest)
    assert parsed_manifest.to_dict() == manifest

    head_material: dict[str, object] = {
        "schema": "sedb-ral.registry-head-receipt/0.1",
        "registry_id": manifest["registry_id"],
        "control_sequence": 0,
        "ledger_event_count": 0,
        "ledger_head": None,
        "last_event_id": None,
        "manifest_digest": manifest["manifest_digest"],
        "previous_control_digest": None,
        "recorded_time_ref": TIME_REF,
        "not_claimed": [
            "resident_registration",
            "external_backup",
            "nonempty_ledger",
        ],
    }
    head = bind_document_digest(head_material, "control_digest")
    parsed_head = RegistryHeadReceipt.from_dict(head)
    assert parsed_head.to_dict() == head

    mutated = copy.deepcopy(head)
    mutated["ledger_event_count"] = 1
    with pytest.raises(RALValidationError) as caught:
        RegistryHeadReceipt.from_dict(mutated)
    assert caught.value.code == "control_digest_mismatch"


def test_constant_uses_only_the_public_registry_boundary():
    assert PRODUCTION_REGISTRY_ROOT == FINAL_ROOT
    assert "AI_HOME" not in PRODUCTION_REGISTRY_ROOT
