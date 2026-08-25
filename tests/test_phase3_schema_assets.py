import copy

import pytest

from sedb_ral.contracts import load_schema, validate_contract
from sedb_ral.errors import RALValidationError

from test_phase3_registration_prepare import (
    IDS,
    valid_claim,
    valid_host_observation,
)


SCHEMA_IDS = {
    "self-application-claim.schema.json": (
        "https://evemisslab.com/schemas/sedb-ral/"
        "self-application-claim.schema.json"
    ),
    "registration-host-observation.schema.json": (
        "https://evemisslab.com/schemas/sedb-ral/"
        "registration-host-observation.schema.json"
    ),
    "prepared-registration.schema.json": (
        "https://evemisslab.com/schemas/sedb-ral/"
        "prepared-registration.schema.json"
    ),
}


@pytest.mark.parametrize("name", sorted(SCHEMA_IDS))
def test_phase3_schema_asset_is_strict_and_has_stable_id(name):
    schema = load_schema(name)
    assert schema["$id"] == SCHEMA_IDS[name]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("self-application-claim.schema.json", valid_claim()),
        (
            "registration-host-observation.schema.json",
            valid_host_observation(),
        ),
    ],
)
def test_phase3_input_schema_accepts_minimal_valid_value(name, value):
    validate_contract(name, value)
    changed = copy.deepcopy(value)
    changed["unexpected"] = True
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract(name, changed)


def test_prepared_schema_accepts_core_output_and_rejects_unknown_fields():
    from sedb_ral.registration import prepare_registration

    value = prepare_registration(
        valid_claim(), valid_host_observation(), IDS
    ).to_dict()
    validate_contract("prepared-registration.schema.json", value)
    value["unexpected"] = True
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("prepared-registration.schema.json", value)
