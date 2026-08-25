from __future__ import annotations

from copy import deepcopy

import pytest

from sedb_ral.registry_root_contracts import bind_document_digest


DIGEST = "sha256:sedb-ral-json-nfc-codepoint-v1:"
CANDIDATE_ID = "9b0c7d46-b94d-4b39-b59f-42f4d458955c"
GENERATION = f"operations-generation:{CANDIDATE_ID}"
TIME_REF = "time:host-wall-clock-unverified:2026-08-26T00:00:00+08:00"
PRODUCTION_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"


def digest(char: str) -> str:
    return DIGEST + char * 64


@pytest.fixture
def base_status() -> dict[str, object]:
    return {
        "schema": "sedb-ral.registry-root-status/0.1",
        "verified": True,
        "registry_id": "registry:dabee562-6af0-496d-94e8-1be9539b32ac",
        "manifest_digest": digest("a"),
        "control_digest": digest("b"),
        "plan_digest": digest("c"),
        "tree_digest": digest("d"),
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
        "private_read_count": 0,
        "network_effect_count": 0,
        "external_effect_count": 0,
    }


@pytest.fixture
def dormant_policy() -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-policy/0.1",
            "policy_id": "policy:production-dormant-v1",
            "allowed_operation_kinds": ["inspect", "status"],
            "intake_enabled": False,
            "execution_enabled": False,
            "capabilities": {
                "ledger_append": False,
                "real_applicant": False,
                "private_access": False,
                "network_send": False,
                "provider_call": False,
                "fabric_emit": False,
                "mcp_call": False,
            },
            "not_claimed": [
                "registrar_authority",
                "resident_registration",
                "private_access",
            ],
        },
        "policy_digest",
    )


def authority_value(plan_digest: str, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "sedb-ral.production-operations-extension-authority/0.1",
        "authority_id": "authority:r3b-b:fixture",
        "principal_ref": "principal:neo.k",
        "operation": "registry.operations-extension.activate",
        "target_root": PRODUCTION_ROOT,
        "operation_plan_digest": plan_digest,
        "scopes": ["registry.operations-extension.activate"],
        "status": "active",
        "issued_time_ref": TIME_REF,
        "expires_time_ref": "time:host-wall-clock-unverified:2026-08-27T00:00:00+08:00",
        "authorship_attestation_ref": "attestation:host-observed:fixture",
        "not_claimed": [
            "resident_approval",
            "ledger_append",
            "private_access",
            "rollback_authority",
        ],
    }
    value.update(deepcopy(updates))
    return bind_document_digest(value, "authority_digest")


def manifest_value(plan: dict[str, object], policy_digest: str) -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-extension-manifest/0.1",
            "extension_kind": "registrar-operations",
            "extension_version": "v1",
            "extension_ref": "extensions/registrar-operations/v1",
            "operations_generation": plan["operations_generation"],
            "registry_id": plan["registry_id"],
            "registry_manifest_digest": plan["registry_manifest_digest"],
            "registry_control_digest": plan["registry_control_digest"],
            "base_tree_digest": plan["base_tree_digest"],
            "dormant_policy_ref": "policies/policy-production-dormant-v1.json",
            "dormant_policy_digest": policy_digest,
            "activation_commit_ref": "ACTIVATION-COMMIT.json",
            "created_time_ref": plan["time_ref"],
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

