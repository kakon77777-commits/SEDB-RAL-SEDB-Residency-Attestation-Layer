from __future__ import annotations

from sedb_ral.registry_root_contracts import bind_document_digest

DIGEST_PREFIX = "sha256:sedb-ral-json-nfc-codepoint-v1:"
REGISTRY_ID = "registry:31e5ee61-2909-4f0d-bdaf-d0aa2f77ed92"
GENERATION = "operations-generation:6f5121df-a649-49f3-a3f8-f1ef7df6f3af"
TIME_REF = "time:synthetic-unavailable:r3b-a"


def digest(character: str) -> str:
    return DIGEST_PREFIX + character * 64


def valid_foreign_pin(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sedb-ral.foreign-schema-pin/0.1",
        "schema_id": "https://example.test/schemas/portable-event.json",
        "schema_version": "0.1",
        "source_repository": "https://example.test/source.git",
        "source_commit": "a" * 40,
        "raw_sha256": "b" * 64,
        "profile_ref": "profile:portable-event-test",
    }
    material.update(overrides)
    return bind_document_digest(material, "pin_digest")


def valid_policy(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sedb-ral.registrar-operations-policy/0.1",
        "policy_id": "operations-policy:synthetic-v1",
        "policy_version": "1",
        "accepted_intake_schemas": ["sedb-ral.registrar-intake/0.1"],
        "accepted_operator_observation_schemas": [
            "sedb-ral.registrar-operator-observation/0.1"
        ],
        "allowed_operation_kinds": [
            "inspect",
            "prepare",
            "plan",
            "execute",
            "reject",
            "withdraw",
            "suspend_address",
            "revoke_authority",
            "status",
            "export_public",
        ],
        "operation_scopes": {
            "execute": "registry.application.accept",
            "revoke_authority": "registry.authority.revoke",
            "suspend_address": "registry.address.suspend",
        },
        "max_p0_bytes": 65536,
        "max_p1_bytes": 4096,
        "checkpoint_required_for": ["execute", "revoke_authority"],
        "lease_seconds": 60,
        "public_fields": [
            "resident_id",
            "status",
            "display_label",
            "addresses",
            "source_event_refs",
            "ledger_head",
        ],
        "capabilities": {
            "production_mutation": False,
            "real_applicant": False,
            "private_access": False,
            "network_send": False,
            "fabric_emit": False,
        },
        "synthetic_only": True,
        "not_claimed": [
            "production_activation",
            "real_applicant",
            "private_access",
            "network_send",
            "fabric_event_emission",
        ],
    }
    material.update(overrides)
    return bind_document_digest(material, "policy_digest")


def valid_intake(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sedb-ral.registrar-intake/0.1",
        "intake_id": "intake:7b5a4b15-52aa-4ac7-9a4f-2e0d5f264b92",
        "claim_ref": "artifact:claim-alpha",
        "claim_digest": digest("1"),
        "host_observation_ref": "artifact:host-alpha",
        "host_observation_digest": digest("2"),
        "prepared_ref": None,
        "prepared_digest": None,
        "sensitivity": "P1",
        "durable_handoff_ref": "handoff:alpha",
        "durable_handoff_digest": digest("3"),
        "received_time_ref": TIME_REF,
        "not_claimed": [
            "prepared",
            "authority_granted",
            "identity_resolved",
            "canonical_commit",
            "private_access",
        ],
    }
    material.update(overrides)
    return bind_document_digest(material, "intake_digest")


def valid_operator_observation(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sedb-ral.registrar-operator-observation/0.1",
        "observation_id": "operator-observation:alpha",
        "task_ref": "codex-thread:synthetic-operator",
        "identifier_kind": "codex_thread",
        "adapter_kind": "synthetic_task_adapter",
        "observed_origin": "host:synthetic-operations-test",
        "principal_ref_claim": "principal:synthetic-operator",
        "authorship_attestation_ref": "attestation:synthetic-operator",
        "verified_attestation_refs": ["attestation:synthetic-operator"],
        "process_evidence_ref": "process-observation:synthetic",
        "unavailable_fields": [],
        "observed_time_ref": TIME_REF,
        "not_claimed": [
            "resident_identity",
            "registrar_authority",
            "private_access",
        ],
    }
    material.update(overrides)
    return bind_document_digest(material, "observation_digest")


def valid_operation_request(**overrides: object) -> dict[str, object]:
    pin = valid_foreign_pin()
    material: dict[str, object] = {
        "schema": "sedb-ral.registrar-operation-request/0.1",
        "operation_id": "operation:75c9559e-0998-4b39-b31d-62e6dadde905",
        "operation_kind": "execute",
        "intake_digest": valid_intake()["intake_digest"],
        "application_digest": digest("4"),
        "target_ref": "resident:synthetic-alpha",
        "authority_artifact_ref": "authority:synthetic-alpha",
        "authority_artifact_digest": digest("5"),
        "operator_observation_ref": "operator-observation:alpha",
        "operator_observation_digest": valid_operator_observation()[
            "observation_digest"
        ],
        "policy_digest": valid_policy()["policy_digest"],
        "operations_generation": GENERATION,
        "registry_id": REGISTRY_ID,
        "registry_manifest_digest": digest("6"),
        "expected_ledger_head": "GENESIS",
        "checkpoint_evidence_ref": "checkpoint:synthetic-alpha",
        "checkpoint_evidence_digest": digest("7"),
        "foreign_evidence_pins": [pin],
        "created_time_ref": TIME_REF,
        "not_claimed": [
            "authority_granted",
            "canonical_commit",
            "identity_resolved",
            "production_activation",
            "private_access",
        ],
    }
    material.update(overrides)
    return bind_document_digest(material, "operation_digest")


def valid_operation_receipt(**overrides: object) -> dict[str, object]:
    request = valid_operation_request()
    material: dict[str, object] = {
        "schema": "sedb-ral.registrar-operation-receipt/0.1",
        "operation_id": request["operation_id"],
        "request_digest": request["operation_digest"],
        "policy_digest": request["policy_digest"],
        "operations_generation": GENERATION,
        "registry_id": REGISTRY_ID,
        "pre_head": None,
        "post_head": digest("8"),
        "outcome": "complete",
        "registrar_receipt_ref": "registrar-receipt:synthetic-alpha",
        "registrar_receipt_digest": digest("9"),
        "projection_ref": "projections/public/synthetic-alpha.json",
        "projection_digest": digest("a"),
        "error_codes": [],
        "side_effect_counters": {
            "synthetic_registry_writes": 1,
            "production_registry_writes": 0,
            "private_reads": 0,
            "network_calls": 0,
            "external_sends": 0,
            "fabric_events": 0,
        },
        "completed_time_ref": TIME_REF,
        "not_claimed": [
            "production_activation",
            "real_applicant",
            "private_access",
            "fabric_adoption",
        ],
    }
    material.update(overrides)
    return bind_document_digest(material, "receipt_digest")


def valid_manifest(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sedb-ral.registrar-operations-manifest/0.1",
        "operations_generation": GENERATION,
        "registry_id": REGISTRY_ID,
        "registry_manifest_digest": digest("b"),
        "registry_control_digest": digest("c"),
        "registry_source_tree_digest": digest("d"),
        "policy_activation_ref": "active-policy/00000000000000000000.json",
        "synthetic_only": True,
        "production_activation": False,
        "fabric_schema_pins": [],
        "created_time_ref": TIME_REF,
        "not_claimed": [
            "production_activation",
            "identity_proof",
            "private_access",
            "federation",
            "deployment",
        ],
    }
    material.update(overrides)
    return bind_document_digest(material, "manifest_digest")


def synthetic_registry_status(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "sedb-ral.registry-root-status/0.1",
        "verified": True,
        "registry_id": REGISTRY_ID,
        "manifest_digest": digest("b"),
        "control_digest": digest("c"),
        "plan_digest": digest("e"),
        "tree_digest": digest("d"),
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
        "private_read_count": 0,
        "network_effect_count": 0,
        "external_effect_count": 0,
    }
    value.update(overrides)
    return value
