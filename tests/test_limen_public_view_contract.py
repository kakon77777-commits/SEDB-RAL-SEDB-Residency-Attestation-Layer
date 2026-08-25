import copy
import hashlib
import json
from pathlib import Path

import pytest

from sedb_ral.contracts import load_schema, validate_contract
from sedb_ral.errors import RALValidationError

ROOT = Path(__file__).parents[1]
SCHEMA_NAME = "limen-ral-view-v0.2.schema.json"
SCHEMA_PATH = ROOT / "src/sedb_ral/schemas" / SCHEMA_NAME
PROFILE_PATH = ROOT / "profiles/limen-ral-view-v0.2-mapping.json"


def valid_task_tool_binding():
    return {
        "binding_id": "binding:address:address:test-alpha-thread",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "identifier_kind": "codex_thread",
        "identifier_components": ["native_thread_id"],
        "native_thread_id": "thread:test-alpha",
        "native_session_id": None,
        "session_match_policy": "not_applicable_for_profile",
        "resident_id": "resident:test-alpha",
        "instance_id": "instance:test-alpha-001",
        "continuity_line_id": "line:test-alpha",
        "speaker_label": "Test Alpha",
        "status": "active",
        "valid_from_sequence": 4,
        "valid_until_sequence": None,
        "lineage_from_thread_ids": [],
        "supersedes_binding_id": None,
        "source_refs": [
            "evt_resident_registered_test_alpha",
            "address:test-alpha-thread",
        ],
    }


def valid_public_view():
    return {
        "schema": "limen.ral-view/0.2",
        "profile": "sedb-ral/0.3.0",
        "view_id": "ral-view:test-alpha",
        "sequence": 4,
        "authority_head": (
            "sha256:sedb-ral-json-nfc-codepoint-v1:" + "1" * 64
        ),
        "binding_head": (
            "sha256:sedb-ral-json-nfc-codepoint-v1:" + "2" * 64
        ),
        "ledger_head": "sha256:sedb-ral-chain-v1:" + "3" * 64,
        "bindings": [valid_task_tool_binding()],
        "projection_conflicts": [],
        "source_refs": [
            "sha256:sedb-ral-chain-v1:" + "3" * 64,
            "evt_resident_registered_test_alpha",
        ],
        "not_claimed": [
            "private_access",
            "host_observation",
            "host_enforcement",
            "registry_authority",
            "identity_merge",
        ],
    }


def load_profile():
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_public_view_v02_accepts_task_tool_thread_only_binding():
    value = valid_public_view()
    binding = value["bindings"][0]

    assert binding["identifier_components"] == ["native_thread_id"]
    assert binding["native_session_id"] is None
    assert binding["session_match_policy"] == (
        "not_applicable_for_profile"
    )
    validate_contract(SCHEMA_NAME, value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("native_session_id", "session:invented"),
        (
            "identifier_components",
            ["native_thread_id", "native_session_id"],
        ),
        ("session_match_policy", "required_exact"),
    ],
)
def test_task_tool_binding_cannot_invent_or_require_a_session(field, value):
    candidate = valid_public_view()
    candidate["bindings"][0][field] = value

    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(SCHEMA_NAME, candidate)


def test_app_server_binding_requires_thread_and_exact_session():
    candidate = valid_public_view()
    binding = candidate["bindings"][0]
    binding.update(
        {
            "adapter_kind": "codex_app_server",
            "identifier_components": [
                "native_thread_id",
                "native_session_id",
            ],
            "native_session_id": "session:test-alpha",
            "session_match_policy": "required_exact",
        }
    )
    validate_contract(SCHEMA_NAME, candidate)

    binding["native_session_id"] = None
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(SCHEMA_NAME, candidate)


def test_public_view_contract_rejects_unknown_fields_at_each_boundary():
    top_level = valid_public_view()
    top_level["private_root"] = "private-root:test-alpha"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(SCHEMA_NAME, top_level)

    binding = valid_public_view()
    binding["bindings"][0]["model_id"] = "model:test"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(SCHEMA_NAME, binding)


def test_public_conflict_is_typed_and_contains_no_identity_winner():
    candidate = valid_public_view()
    candidate["bindings"] = []
    candidate["projection_conflicts"] = [
        {
            "conflict_id": "conflict:thread:test-alpha",
            "error_code": "address_binding_conflict",
            "namespace": "codex_thread",
            "locator": "thread:test-alpha",
            "binding_refs": [
                "address:test-alpha-thread",
                "address:test-beta-thread",
            ],
            "source_refs": [
                "evt_resident_registered_test_alpha",
                "evt_resident_registered_test_beta",
            ],
        }
    ]

    validate_contract(SCHEMA_NAME, candidate)
    assert "resident_id" not in candidate["projection_conflicts"][0]


def test_mapping_profile_pins_actual_contract_bytes_and_exact_adapters():
    profile = load_profile()

    assert profile["profile_id"] == "limen-ral-view-v0.2-mapping"
    assert profile["profile_version"] == "1"
    assert profile["contract_schema"] == "limen.ral-view/0.2"
    assert profile["contract_sha256"] == hashlib.sha256(
        SCHEMA_PATH.read_bytes()
    ).hexdigest()
    assert profile["adapter_mappings"] == [
        {
            "source_namespace": "codex_thread",
            "source_adapter_kind": "codex_app_task_tool",
            "provider": "openai",
            "identifier_kind": "codex_thread",
            "identifier_components": ["native_thread_id"],
            "session_match_policy": "not_applicable_for_profile",
        },
        {
            "source_namespace": "codex_thread",
            "source_adapter_kind": "codex_app_server",
            "provider": "openai",
            "identifier_kind": "codex_thread",
            "identifier_components": [
                "native_thread_id",
                "native_session_id",
            ],
            "session_match_policy": "required_exact",
        },
    ]


def test_profile_and_contract_have_no_private_or_host_observation_fields():
    contract = load_schema(SCHEMA_NAME)
    profile = load_profile()
    serialized = json.dumps(
        {"contract": contract, "profile": profile}, sort_keys=True
    )

    for forbidden in (
        "private_root",
        "private_manifest",
        "applicant_claim",
        "native_turn_id",
        "model_id",
        "principal_ref",
    ):
        assert forbidden not in serialized


def test_contract_rejects_mutation_without_changing_test_fixture():
    original = valid_public_view()
    candidate = copy.deepcopy(original)
    candidate["not_claimed"].remove("private_access")

    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(SCHEMA_NAME, candidate)
    validate_contract(SCHEMA_NAME, original)
