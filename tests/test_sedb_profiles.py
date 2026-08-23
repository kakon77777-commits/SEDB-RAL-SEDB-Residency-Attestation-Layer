import json
from pathlib import Path

import pytest

from sedb_ral.contracts import validate_contract
from sedb_ral.errors import RALValidationError

ROOT = Path(__file__).parents[1]
SCHEMA_ROOT = ROOT / "src" / "sedb_ral" / "schemas"


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_adoption_profile_pins_exact_package():
    profile = load("profiles/sedb-v0.4b-adoption.json")

    assert profile["archive_sha256"] == (
        "159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8"
    )
    assert profile["package_version"] == "0.4.0b1"
    assert profile["source_commit"] == "139b9952bb283b2e95f7690d76e3c5fbcdc680aa"
    assert profile["adoption_status"] == "candidate"
    validate_contract(
        "sedb-adoption.schema.json", profile, schema_root=SCHEMA_ROOT
    )


def test_mapping_has_one_rule_per_projected_value():
    mapping = load("profiles/sedb-v0.4b-mapping.json")

    assert {rule["classification"] for rule in mapping["rules"]} == {
        "mapped",
        "intentionally_unmapped",
    }
    assert {
        rule["sedb_target"]
        for rule in mapping["rules"]
        if rule["classification"] == "mapped"
    } == {
        "sedb_ral.resident_id",
        "sedb_ral.application_id",
        "sedb_ral.application_status",
        "sedb_ral.instance_refs",
        "sedb_ral.addresses",
        "sedb_ral.claims",
        "sedb_ral.attestations",
        "sedb_ral.ledger_head",
    }
    assert sum(
        rule["classification"] == "mapped" for rule in mapping["rules"]
    ) == 8
    assert next(
        rule for rule in mapping["rules"]
        if rule["classification"] == "intentionally_unmapped"
    )["sedb_target"] is None
    validate_contract(
        "sedb-compatibility-receipt.schema.json",
        {
            "schema_version": "0.1",
            "receipt_id": "sedb-receipt:test:1",
            "adoption_profile_id": "sedb-v0.4b-adoption",
            "adoption_profile_version": "1",
            "mapping_profile_id": "sedb-v0.4b-mapping",
            "mapping_profile_version": "1",
            "compatibility_status": "compatible",
            "adoption_status": "adopted",
            "evidence_refs": ["evidence:test:compatibility"],
        },
        schema_root=SCHEMA_ROOT,
    )


@pytest.mark.parametrize(
    "fixture_name",
    ["wrong-archive-hash.json", "wrong-source-commit.json"],
)
def test_corrupted_adoption_fixtures_fail_the_pinned_contract(fixture_name):
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(
            "sedb-adoption.schema.json",
            load(f"fixtures/sedb/{fixture_name}"),
            schema_root=SCHEMA_ROOT,
        )


def test_unobserved_archive_facts_are_never_coerced_to_false():
    profile = load("profiles/sedb-v0.4b-adoption.json")
    profile["archive_size"] = False

    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(
            "sedb-adoption.schema.json", profile, schema_root=SCHEMA_ROOT
        )
