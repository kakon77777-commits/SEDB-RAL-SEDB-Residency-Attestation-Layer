import copy
import json
from pathlib import Path

import pytest

import sedb_ral.application as application_module
from sedb_ral.application import (
    application_digest,
    evaluate_application,
)

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


def test_application_reference_validator_accepts_the_positive_control():
    fixture = load("authorized-zero-address.json")

    assert application_module.validate_application_references(
        fixture["application"]
    ) == ()


@pytest.mark.parametrize(
    ("corrupt", "expected_code"),
    [
        (
            lambda application: application["instance_claims"][0].update(
                resident_ref="resident:other"
            ),
            "application_instance_resident_mismatch",
        ),
        (
            lambda application: application["addresses"].append(
                {
                    "schema_version": "0.1",
                    "address_id": "address:test:1",
                    "namespace": "codex_thread",
                    "adapter_kind": "codex_queue",
                    "locator": "019fe51e-9276-7f63-8c16-414624b7fa9d",
                    "target_ref": "resident:other",
                    "status": "active",
                }
            ),
            "application_address_target_mismatch",
        ),
        (
            lambda application: application["claims"][0].update(
                subject_ref="resident:other"
            ),
            "application_claim_subject_mismatch",
        ),
        (
            lambda application: application["claims"][0].update(
                claimant_ref="resident:other"
            ),
            "application_claim_claimant_mismatch",
        ),
        (
            lambda application: application["claims"][0].update(
                claimed_authored_by_instance="instance:undeclared"
            ),
            "application_claim_instance_undeclared",
        ),
        (
            lambda application: application["claims"][0].update(
                claimed_on_behalf_of_line="line:undeclared"
            ),
            "application_on_behalf_unsupported",
        ),
        (
            lambda application: application["instance_claims"].append(
                copy.deepcopy(application["instance_claims"][0])
            ),
            "application_instance_id_duplicate",
        ),
        (
            lambda application: application["addresses"].extend(
                [
                    {
                        "schema_version": "0.1",
                        "address_id": "address:test:1",
                        "namespace": "codex_thread",
                        "adapter_kind": "codex_queue",
                        "locator": "thread:first",
                        "target_ref": "resident:test",
                        "status": "active",
                    },
                    {
                        "schema_version": "0.1",
                        "address_id": "address:test:1",
                        "namespace": "codex_thread",
                        "adapter_kind": "codex_queue",
                        "locator": "thread:second",
                        "target_ref": "resident:test",
                        "status": "active",
                    },
                ]
            ),
            "application_address_id_duplicate",
        ),
        (
            lambda application: application["claims"].append(
                copy.deepcopy(application["claims"][0])
            ),
            "application_claim_id_duplicate",
        ),
    ],
)
def test_each_application_relationship_is_the_sole_corrupted_term(
    corrupt, expected_code
):
    fixture = load("authorized-zero-address.json")
    application = copy.deepcopy(fixture["application"])
    corrupt(application)

    result = evaluate_application(
        application,
        fixture["authorities"],
        verified_attestation_refs=VERIFIED,
    )

    assert result.decision == "defer"
    assert result.reason_codes == (expected_code,)


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


def test_exact_acceptance_scope_must_be_requested_even_when_substitute_matches():
    fixture = load("authorized-zero-address.json")
    application = copy.deepcopy(fixture["application"])
    authority = copy.deepcopy(fixture["authorities"][0])
    application["requested_scopes"] = ["registry.application.inspect"]
    authority["scopes"] = ["registry.application.inspect"]

    result = evaluate_application(
        application,
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
