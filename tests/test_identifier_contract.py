import json
from pathlib import Path

import pytest

from sedb_ral.contracts import validate_contract
from sedb_ral.errors import RALValidationError

ROOT = Path(__file__).parents[1]


def load_fixture(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "relative",
    [
        "fixtures/identifier/positive/resident-address.json",
        "fixtures/identifier/negative/shared-runtime-tag.json",
        "fixtures/identifier/mixed_population/one-resident.json",
    ],
)
def test_population_fixture_matches_contract(relative):
    validate_contract(
        "identifier-discrimination.schema.json",
        load_fixture(relative),
    )


def test_embedded_identifier_matches_field_contract():
    fixture = load_fixture(
        "fixtures/identifier/positive/resident-address.json"
    )
    validate_contract(
        "identifier-field.schema.json", fixture["identifier_exemplar"]
    )


def test_unknown_identifier_field_is_rejected():
    fixture = load_fixture(
        "fixtures/identifier/positive/resident-address.json"
    )
    fixture["identifier_exemplar"]["seat"] = "overloaded"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("identifier-discrimination.schema.json", fixture)


def test_legacy_identifier_property_is_rejected_before_release():
    fixture = load_fixture(
        "fixtures/identifier/positive/resident-address.json"
    )
    fixture["identifier"] = fixture.pop("identifier_exemplar")
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("identifier-discrimination.schema.json", fixture)


def test_fixture_requires_retro_stamp_status_when_retrospective():
    fixture = load_fixture(
        "fixtures/identifier/negative/shared-runtime-tag.json"
    )
    del fixture["temporal_evidence"]["retro_stamped"]
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("identifier-discrimination.schema.json", fixture)


def test_non_retrospective_fixture_cannot_claim_retro_stamp():
    fixture = load_fixture(
        "fixtures/identifier/positive/resident-address.json"
    )
    fixture["temporal_evidence"]["retro_stamped"] = True
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("identifier-discrimination.schema.json", fixture)
