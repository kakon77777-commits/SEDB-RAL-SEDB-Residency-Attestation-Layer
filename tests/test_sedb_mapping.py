import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.projection import RegistryProjection
from sedb_ral.sedb_mapping import project_to_sedb_records


ROOT = Path(__file__).parents[1]
EXPECTED = ROOT / "fixtures" / "sedb" / "expected-resident.jsonl"
MAPPING = json.loads(
    (ROOT / "profiles" / "sedb-v0.4b-mapping.json").read_text(encoding="utf-8")
)
CLAIM = {
    "schema_version": "0.1",
    "claim_id": "claim:test:1",
    "claimant_ref": "resident:test",
    "subject_ref": "resident:test",
    "predicate": "display_label",
    "object": "Test Resident",
    "claimed_time": None,
    "claimed_authored_by_instance": "instance:test:1",
    "claimed_on_behalf_of_line": None,
}
INSTANCE = {
    "schema_version": "0.1",
    "instance_id": "instance:test:1",
    "resident_ref": "resident:test",
    "runtime_tag": "runtime:claude-code",
    "started_time_ref": "ctcl:instant:test",
    "ended_time_ref": None,
}
SOURCE_ADDRESS = {
    "address_id": "address:source:1",
    "kind": "queue",
    "value": "queue:source",
}
PROJECTION = RegistryProjection(
    applications={"application:test:1": {"status": "accepted"}},
    residents={
        "resident:test": {
            "resident_id": "resident:test",
            "application_ref": "application:test:1",
            "display_label": "Test Resident",
            "instances": [INSTANCE],
            "addresses": [],
            "claims": [CLAIM],
        }
    },
    directory={
        "resident:test": {
            "instance_refs": ["instance:test:1"],
            "addresses": [],
        }
    },
    claims={"claim:test:1": CLAIM},
    resident_source_event_ids={"resident:test": "evt:resident:1"},
    applied_corrections=(),
    unapplied_event_ids=(),
    unapplied_reasons={},
    source_event_ids=("evt:authority:1", "evt:resident:1"),
)


def test_resident_projection_matches_hand_derived_record():
    records = project_to_sedb_records(PROJECTION, MAPPING)

    assert canonical_bytes(records[0]) == EXPECTED.read_bytes().rstrip(b"\n")


def test_missing_address_remains_absent_not_false():
    record = project_to_sedb_records(PROJECTION, MAPPING)[0]

    assert "ral.addresses" not in record["values"]


def test_resident_source_addresses_and_instances_win_over_directory_copy():
    second_instance = {
        **INSTANCE,
        "instance_id": "instance:test:2",
    }
    projection = replace(
        PROJECTION,
        residents={
            "resident:test": {
                **PROJECTION.residents["resident:test"],
                "addresses": [SOURCE_ADDRESS],
                "instances": [second_instance, INSTANCE],
            }
        },
        directory={
            "resident:test": {
                "addresses": [{"address_id": "address:directory:1"}],
                "instance_refs": ["instance:directory:1"],
            }
        },
    )

    values = project_to_sedb_records(projection, MAPPING)[0]["values"]
    assert values["ral.addresses"] == [SOURCE_ADDRESS]
    assert values["ral.instance_refs"] == [
        "instance:test:1",
        "instance:test:2",
    ]


def test_empty_resident_attestations_are_emitted_honestly():
    record = project_to_sedb_records(PROJECTION, MAPPING)[0]

    assert record["values"]["ral.attestations"] == []


def test_resident_records_sort_by_canonical_id():
    second = copy.deepcopy(PROJECTION.residents["resident:test"])
    second["resident_id"] = "resident:alpha"
    second["application_ref"] = "application:alpha"
    second["display_label"] = "Alpha Resident"
    projection = replace(
        PROJECTION,
        applications={
            "application:test:1": {"status": "accepted"},
            "application:alpha": {"status": "accepted"},
        },
        residents={"resident:test": PROJECTION.residents["resident:test"], "resident:alpha": second},
        directory={
            "resident:test": PROJECTION.directory["resident:test"],
            "resident:alpha": {"instance_refs": [], "addresses": []},
        },
    )

    assert [record["id"] for record in project_to_sedb_records(projection, MAPPING)] == [
        "resident:alpha",
        "resident:test",
    ]


def test_explicit_null_value_follows_preserve_null_policy():
    projection = replace(
        PROJECTION,
        residents={
            "resident:test": {
                **PROJECTION.residents["resident:test"],
                "addresses": None,
            }
        },
        directory={
            "resident:test": {
                **PROJECTION.directory["resident:test"],
                "addresses": None,
            }
        },
    )

    assert project_to_sedb_records(projection, MAPPING)[0]["values"][
        "ral.addresses"
    ] is None


def test_unknown_mapping_rule_turns_red():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"].append(
        {
            "rule_id": "future-field",
            "ral_path": "ral.future_field",
            "sedb_target": "sedb_ral.future_field",
            "value_transform": "identity",
            "null_policy": "preserve_null",
            "classification": "mapped",
            "reason": "must not silently project undeclared values",
        }
    )

    with pytest.raises(RALValidationError, match="sedb_mapping_rule_unknown"):
        project_to_sedb_records(PROJECTION, mapping)


def test_missing_declared_mapping_rule_turns_red():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"] = [
        rule for rule in mapping["rules"] if rule["ral_path"] != "ral.claims"
    ]

    with pytest.raises(RALValidationError, match="sedb_mapping_rule_missing"):
        project_to_sedb_records(PROJECTION, mapping)


def test_missing_intentionally_unmapped_rule_turns_red():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"] = [
        rule for rule in mapping["rules"] if rule["ral_path"] != "ral.authority"
    ]

    with pytest.raises(RALValidationError, match="sedb_mapping_rule_missing"):
        project_to_sedb_records(PROJECTION, mapping)


def test_null_policy_violation_turns_red():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"][0]["null_policy"] = "drop_null"

    with pytest.raises(
        RALValidationError, match="sedb_mapping_null_policy_invalid"
    ):
        project_to_sedb_records(PROJECTION, mapping)
