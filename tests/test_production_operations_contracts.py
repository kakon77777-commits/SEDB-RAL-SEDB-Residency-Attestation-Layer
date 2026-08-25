from __future__ import annotations

from copy import deepcopy

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.production_operations_contracts import (
    EXTENSION_REF,
    PRODUCTION_ROOT,
    ProductionOperationsAuthority,
    ProductionOperationsManifest,
    ProductionOperationsPlan,
    plan_production_operations_extension,
    verify_production_operations_authority,
)
from sedb_ral.registry_root_contracts import bind_document_digest
from production_operations_helpers import (
    CANDIDATE_ID,
    GENERATION,
    TIME_REF,
    authority_value,
    base_status,
    digest,
    dormant_policy,
    manifest_value,
)


def plan_value(base_status, dormant_policy):
    return plan_production_operations_extension(
        registry_status=base_status,
        candidate_id=CANDIDATE_ID,
        operations_generation=GENERATION,
        policy_digest=dormant_policy["policy_digest"],
        source_commit="2470be770962556998925a739c3d1099dc830786",
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity="volume:sha256:" + "1" * 64,
        expected_owner_sid="S-1-5-21-1000",
        acl_fingerprint=digest("2"),
        pre_checkpoint_digest=digest("3"),
        time_ref=TIME_REF,
    )


def test_plan_binds_exact_empty_production_root(base_status, dormant_policy):
    value = plan_value(base_status, dormant_policy)

    assert value["final_root"] == PRODUCTION_ROOT
    assert value["extension_ref"] == EXTENSION_REF
    assert value["candidate_name"] == f".SEDB-RAL.operations-{CANDIDATE_ID}"
    assert value["required_counts"] == {
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
    }
    assert ProductionOperationsPlan.from_dict(value).digest == value["plan_digest"]


@pytest.mark.parametrize(
    "field",
    ["ledger_event_count", "application_count", "resident_count", "address_count"],
)
def test_plan_refuses_nonempty_registry(base_status, dormant_policy, field):
    base_status[field] = 1

    with pytest.raises(RALValidationError, match="production_operations_registry_not_empty"):
        plan_value(base_status, dormant_policy)


def test_plan_refuses_generation_not_bound_to_candidate(base_status, dormant_policy):
    with pytest.raises(RALValidationError, match="production_operations_generation_mismatch"):
        plan_production_operations_extension(
            registry_status=base_status,
            candidate_id=CANDIDATE_ID,
            operations_generation="operations-generation:other",
            policy_digest=dormant_policy["policy_digest"],
            source_commit="2470be770962556998925a739c3d1099dc830786",
            source_package_version="0.5.0b1",
            filesystem="NTFS",
            volume_identity="volume:sha256:" + "1" * 64,
            expected_owner_sid="S-1-5-21-1000",
            acl_fingerprint=digest("2"),
            pre_checkpoint_digest=digest("3"),
            time_ref=TIME_REF,
        )


def test_plan_unknown_field_is_rejected(base_status, dormant_policy):
    value = plan_value(base_status, dormant_policy)
    material = dict(value)
    material.pop("plan_digest")
    material["private_path"] = r"D:\AI_RESIDENCE\AI_HOME"
    changed = bind_document_digest(material, "plan_digest")

    with pytest.raises(RALValidationError):
        ProductionOperationsPlan.from_dict(changed)


def test_authority_binds_only_exact_activation(base_status, dormant_policy):
    plan = plan_value(base_status, dormant_policy)
    authority = authority_value(plan["plan_digest"])

    verified = verify_production_operations_authority(
        authority,
        plan_digest=plan["plan_digest"],
        exact_root=PRODUCTION_ROOT,
    )

    assert verified["operation"] == "registry.operations-extension.activate"
    assert ProductionOperationsAuthority.from_dict(authority).digest == authority["authority_digest"]


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"operation": "resident.register"}, "production_operations_authority_mismatch"),
        ({"target_root": r"D:\AI_RESIDENCE\AI_HOME"}, "production_operations_authority_mismatch"),
        ({"operation_plan_digest": digest("9")}, "production_operations_authority_mismatch"),
        ({"status": "revoked"}, "production_operations_authority_inactive"),
        ({"scopes": ["registry.operations-extension.activate", "ledger.append"]}, "production_operations_authority_scope_invalid"),
    ],
)
def test_authority_refuses_broader_or_inactive_grant(
    base_status, dormant_policy, updates, code
):
    plan = plan_value(base_status, dormant_policy)
    authority = authority_value(plan["plan_digest"], **updates)

    with pytest.raises(RALValidationError, match=code):
        verify_production_operations_authority(
            authority,
            plan_digest=plan["plan_digest"],
            exact_root=PRODUCTION_ROOT,
        )


def test_manifest_is_dormant_and_cannot_enable_execution(base_status, dormant_policy):
    plan = plan_value(base_status, dormant_policy)
    value = manifest_value(plan, dormant_policy["policy_digest"])
    manifest = ProductionOperationsManifest.from_dict(value)
    assert manifest.to_dict()["execution_enabled"] is False

    changed = deepcopy(value)
    changed.pop("manifest_digest")
    changed["execution_enabled"] = True
    changed = bind_document_digest(changed, "manifest_digest")
    with pytest.raises(RALValidationError):
        ProductionOperationsManifest.from_dict(changed)
