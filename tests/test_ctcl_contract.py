import copy
import json
from pathlib import Path

import pytest

from sedb_ral.ctcl import validate_ctcl_receipt
from sedb_ral.errors import RALValidationError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ctcl"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_reading_is_valid_local_evidence_but_not_retrievable():
    value = load("reading.json")
    validate_ctcl_receipt(value)
    assert value["ctcl_call_kind"] == "reading"
    assert value["retrievability"]["expected"] is False


def test_reading_cannot_claim_verified_retrieval():
    value = copy.deepcopy(load("reading.json"))
    value["retrievability"] = {
        "expected": True,
        "status": "verified",
        "checked_at_ref": "ctcl:instant:check",
        "retrieval_evidence_ref": "evidence:check",
    }
    with pytest.raises(RALValidationError, match="reading_not_retrievable"):
        validate_ctcl_receipt(value)


def test_registered_anchor_can_be_verified_retrievable():
    validate_ctcl_receipt(load("registered-anchor.json"))


def test_reading_cannot_carry_a_service_returned_share_url():
    value = copy.deepcopy(load("reading.json"))
    value["service_returned_share_url"] = (
        "https://commoninstant.org/i/fabricated"
    )
    with pytest.raises(RALValidationError, match="reading_share_url_invalid"):
        validate_ctcl_receipt(value)


def test_verified_retrieval_requires_evidence_ref():
    value = copy.deepcopy(load("registered-anchor.json"))
    value["retrievability"]["retrieval_evidence_ref"] = None
    with pytest.raises(RALValidationError, match="retrieval_evidence_missing"):
        validate_ctcl_receipt(value)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("unix_ms", "1"),
        ("unix_us", "1"),
        ("unix_s", "1"),
        ("rfc3339", "2026-08-23T08:09:40.165Z"),
    ],
)
def test_all_time_encodings_must_agree(field, bad_value):
    value = copy.deepcopy(load("registered-anchor.json"))
    value["encodings"][field] = bad_value
    with pytest.raises(RALValidationError, match="encoding_mismatch"):
        validate_ctcl_receipt(value)


def test_registered_anchor_requires_service_returned_share_url():
    value = copy.deepcopy(load("registered-anchor.json"))
    value["service_returned_share_url"] = None
    with pytest.raises(RALValidationError, match="anchor_share_url_missing"):
        validate_ctcl_receipt(value)


def test_reference_time_must_match_rfc3339_encoding():
    value = copy.deepcopy(load("registered-anchor.json"))
    value["reference"]["value"] = "2026-08-23T08:09:40.165Z"
    with pytest.raises(RALValidationError, match="encoding_mismatch"):
        validate_ctcl_receipt(value)


def test_signature_presence_remains_unverified():
    value = load("registered-anchor.json")
    assert value["signature"]["verification_status"] == "not_performed"
