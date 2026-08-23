import copy
import json
from pathlib import Path

import pytest

from sedb_ral.contracts import load_schema, validate_contract
from sedb_ral.errors import RALValidationError

TIME = "ctcl:instant:03a45699-68b2-4578-99e4-ef83a626c30d"
ROOT = Path(__file__).parents[1]

INSTANCE = {
    "schema_version": "0.1",
    "instance_id": "instance:test:1",
    "resident_ref": "resident:test",
    "runtime_tag": "runtime:claude-code",
    "started_time_ref": TIME,
    "ended_time_ref": None,
}
ADDRESS = {
    "schema_version": "0.1",
    "address_id": "address:test:1",
    "namespace": "codex_thread",
    "adapter_kind": "codex_queue",
    "locator": "019fe51e-9276-7f63-8c16-414624b7fa9d",
    "target_ref": "resident:test",
    "status": "active",
}
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
APPLICATION = {
    "schema_version": "0.1",
    "application_id": "application:test:1",
    "claimed_resident_id": "resident:test",
    "display_label": "Test Resident",
    "instance_claims": [INSTANCE],
    "addresses": [],
    "claims": [CLAIM],
    "submitted_time_ref": TIME,
    "requested_scopes": ["registry.application.accept"],
}
RESIDENT = {
    "schema_version": "0.1",
    "resident_id": "resident:test",
    "display_label": "Test Resident",
    "status": "active",
    "application_ref": "application:test:1",
    "identifier_refs": ["id:resident-address:v1"],
}
BINDING = {
    "schema_version": "0.1",
    "binding_id": "binding:test:1",
    "subject_ref": "resident:test",
    "object_kind": "address",
    "object_ref": "address:test:1",
    "valid_from_event": "evt_001",
    "valid_until_event": None,
}
OBSERVATION = {
    "schema_version": "0.1",
    "observation_id": "observation:test:1",
    "observer_ref": "adapter:codex_queue",
    "subject_ref": "delivery:test:1",
    "source_expression": "codex queue exit status",
    "measurement_scope": "one invocation at one recorded time",
    "observed_value": {"transport_accepted": True},
    "observed_time_ref": TIME,
    "claimed_origin": "resident:test",
    "observed_origin": None,
}
ATTESTATION = {
    "schema_version": "0.1",
    "attestation_id": "attestation:test:1",
    "claim_ref": "claim:test:1",
    "evidence_basis": "own_execution",
    "evidence_root_refs": ["evidence:root:1"],
    "derivation_parent_refs": [],
    "independence_status": "independent",
    "verification_status": "verified",
}
AUTHORITY = {
    "schema_version": "0.1",
    "authority_id": "authority:test:1",
    "principal_ref": "principal:neo.k",
    "subject_kind": "resident_id",
    "subject_ref": "resident:test",
    "scopes": ["registry.application.accept"],
    "status": "active",
    "issued_time_ref": TIME,
    "revoked_by_event": None,
    "authorship_attestation_ref": "attestation:neo:1",
}
CORRECTION = {
    "schema_version": "0.1",
    "correction_id": "correction:test:1",
    "target_event_id": "evt_001",
    "action": "correct",
    "replacement_ref": "claim:test:2",
    "reason": "corrected display label",
}
INCIDENT = {
    "id": 3,
    "cls": "A",
    "title": "probe emitted runtime tag as seat",
    "actor_claim": "準繩",
    "origin_strength": "own_execution",
    "scope": "two measured sessions",
    "why": "byte-identical result",
    "status": "fixed",
    "temporal_capture_mode": "retrospective",
    "retro_stamped": True,
    "observed_time_ref": None,
    "recorded_time_ref": TIME,
    "fix": "renamed runtime_tag",
}

VALID = {
    "application.schema.json": APPLICATION,
    "resident.schema.json": RESIDENT,
    "instance.schema.json": INSTANCE,
    "address.schema.json": ADDRESS,
    "binding.schema.json": BINDING,
    "claim.schema.json": CLAIM,
    "observation.schema.json": OBSERVATION,
    "attestation.schema.json": ATTESTATION,
    "authority-envelope.schema.json": AUTHORITY,
    "correction-tombstone.schema.json": CORRECTION,
    "incident-record.schema.json": INCIDENT,
}


@pytest.mark.parametrize("name", sorted(VALID))
def test_phase1b_schema_loads_and_validates_minimal_value(name):
    schema = load_schema(name)
    assert schema["additionalProperties"] is False
    validate_contract(name, VALID[name])


@pytest.mark.parametrize("name", sorted(VALID))
def test_phase1b_contract_rejects_unknown_fields(name):
    value = copy.deepcopy(VALID[name])
    value["unexpected"] = True
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(name, value)


def test_zero_addresses_is_valid_but_omission_is_not():
    validate_contract("application.schema.json", APPLICATION)
    value = copy.deepcopy(APPLICATION)
    del value["addresses"]
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("application.schema.json", value)


def test_observed_origin_null_is_not_false():
    validate_contract("observation.schema.json", OBSERVATION)
    value = copy.deepcopy(OBSERVATION)
    value["observed_origin"] = False
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("observation.schema.json", value)


def test_attestation_independence_is_categorical():
    for status in ("independent", "shared_root", "indeterminate", "unmeasured"):
        value = copy.deepcopy(ATTESTATION)
        value["independence_status"] = status
        validate_contract("attestation.schema.json", value)
    value = copy.deepcopy(ATTESTATION)
    value["independence_status"] = True
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("attestation.schema.json", value)


def test_application_cannot_request_an_identity_merge():
    value = copy.deepcopy(APPLICATION)
    value["continuity_merge_target"] = "resident:other"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("application.schema.json", value)


@pytest.mark.parametrize(
    "name",
    [
        "authorized-zero-address.json",
        "missing-authority.json",
        "revoked-authority.json",
    ],
)
def test_application_decision_fixtures_use_valid_contract_values(name):
    value = json.loads(
        (ROOT / "fixtures/application" / name).read_text(encoding="utf-8")
    )
    validate_contract("application.schema.json", value["application"])
    for authority in value["authorities"]:
        validate_contract("authority-envelope.schema.json", authority)


@pytest.mark.parametrize(
    "changes",
    [
        {"retro_stamped": True, "temporal_capture_mode": "contemporaneous"},
        {"retro_stamped": True, "observed_time_ref": TIME},
        {"retro_stamped": False, "temporal_capture_mode": "retrospective"},
        {"retro_stamped": False, "observed_time_ref": None},
        {"recorded_time_ref": "yesterday afternoon"},
        {"observed_time_ref": "sometime last week"},
    ],
)
def test_incident_temporal_contradictions_are_rejected(changes):
    value = copy.deepcopy(INCIDENT)
    value.update(changes)
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("incident-record.schema.json", value)


def test_contemporaneous_incident_requires_a_real_observed_instant():
    value = copy.deepcopy(INCIDENT)
    value.update(
        {
            "retro_stamped": False,
            "temporal_capture_mode": "contemporaneous",
            "observed_time_ref": TIME,
        }
    )
    validate_contract("incident-record.schema.json", value)
