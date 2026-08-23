import copy
import json
from pathlib import Path

from sedb_ral.application import application_digest, evaluate_application

ROOT = Path(__file__).parents[1]
VERIFIED = frozenset({"attestation:neo:1"})


def load(name: str):
    return json.loads(
        (ROOT / "fixtures/application" / name).read_text(encoding="utf-8")
    )


def test_authorized_zero_address_application_is_accepted_candidate():
    fixture = load("authorized-zero-address.json")
    result = evaluate_application(
        fixture["application"],
        fixture["authorities"],
        verified_attestation_refs=VERIFIED,
    )
    assert result.decision == "accept"
    assert result.reason_codes == ("authority_sufficient",)
    assert result.authority_ref == "authority:test:1"
    assert result.mutated is False


def test_missing_authority_defers_without_mutation():
    fixture = load("missing-authority.json")
    result = evaluate_application(
        fixture["application"],
        fixture["authorities"],
        verified_attestation_refs=VERIFIED,
    )
    assert result.decision == "defer"
    assert result.reason_codes == ("authority_missing",)
    assert result.mutated is False


def test_revoked_authority_defers_without_mutation():
    fixture = load("revoked-authority.json")
    result = evaluate_application(
        fixture["application"],
        fixture["authorities"],
        verified_attestation_refs=VERIFIED,
    )
    assert result.decision == "defer"
    assert result.reason_codes == ("authority_revoked",)


def test_unverified_principal_authorship_cannot_authorize():
    fixture = load("authorized-zero-address.json")
    result = evaluate_application(
        fixture["application"],
        fixture["authorities"],
        verified_attestation_refs=frozenset(),
    )
    assert result.decision == "defer"
    assert result.reason_codes == ("authority_authorship_unverified",)


def test_application_digest_authority_binds_exact_bytes():
    fixture = load("authorized-zero-address.json")
    authority = copy.deepcopy(fixture["authorities"][0])
    authority["subject_kind"] = "application_digest"
    authority["subject_ref"] = application_digest(fixture["application"])
    accepted = evaluate_application(
        fixture["application"],
        [authority],
        verified_attestation_refs=VERIFIED,
    )
    assert accepted.decision == "accept"

    changed = copy.deepcopy(fixture["application"])
    changed["display_label"] = "Different"
    deferred = evaluate_application(
        changed,
        [authority],
        verified_attestation_refs=VERIFIED,
    )
    assert deferred.reason_codes == ("authority_missing",)


def test_authority_scope_must_cover_every_requested_scope():
    fixture = load("authorized-zero-address.json")
    authority = copy.deepcopy(fixture["authorities"][0])
    authority["scopes"] = ["registry.application.inspect"]
    result = evaluate_application(
        fixture["application"],
        [authority],
        verified_attestation_refs=VERIFIED,
    )
    assert result.decision == "defer"
    assert result.reason_codes == ("authority_scope_missing",)


def test_multiple_matching_authorities_fail_ambiguous():
    fixture = load("authorized-zero-address.json")
    second = copy.deepcopy(fixture["authorities"][0])
    second["authority_id"] = "authority:test:2"
    result = evaluate_application(
        fixture["application"],
        [fixture["authorities"][0], second],
        verified_attestation_refs=VERIFIED,
    )
    assert result.decision == "defer"
    assert result.reason_codes == ("authority_ambiguous",)
