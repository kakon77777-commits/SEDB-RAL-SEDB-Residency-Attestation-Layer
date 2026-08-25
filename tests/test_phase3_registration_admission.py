import copy
from dataclasses import replace

import pytest
from test_phase3_registration_prepare import (
    IDS,
    valid_claim,
    valid_host_observation,
)

from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.projection import RegistryProjection, continuity_line_for
from sedb_ral.registration import prepare_registration
from sedb_ral.registration_admission import evaluate_prepared_registration

VERIFIED = frozenset({"attestation:test-principal"})


def prepared_registration(**claim_changes):
    return prepare_registration(
        valid_claim(**claim_changes), valid_host_observation(), IDS
    )


def authority_for(prepared, **changes):
    value = {
        "schema_version": "0.1",
        "authority_id": "authority:test-principal",
        "principal_ref": "principal:test",
        "subject_kind": "application_digest",
        "subject_ref": prepared.application_digest,
        "scopes": ["registry.application.accept"],
        "status": "active",
        "issued_time_ref": "ctcl:instant:test-authority",
        "revoked_by_event": None,
        "authorship_attestation_ref": "attestation:test-principal",
    }
    value.update(changes)
    return value


def empty_projection():
    return RegistryProjection(
        applications={},
        residents={},
        directory={},
        claims={},
        resident_source_event_ids={},
        applied_corrections=(),
        unapplied_event_ids=(),
        unapplied_reasons={},
        source_event_ids=(),
    )


def existing_resident(
    *,
    resident_id="resident:test-other",
    label="Other Resident",
    locator=None,
    address_status="active",
    line_id="line:test-other",
    second_line_id=None,
):
    instance_id = f"instance:{resident_id}:existing"
    addresses = []
    if locator is not None:
        addresses.append(
            {
                "schema_version": "0.1",
                "address_id": f"address:{resident_id}:existing",
                "namespace": "codex_thread",
                "adapter_kind": "codex_app_task_tool",
                "locator": locator,
                "target_ref": resident_id,
                "status": address_status,
            }
        )
    claims = [
        {
            "schema_version": "0.1",
            "claim_id": f"claim:{resident_id}:line",
            "claimant_ref": resident_id,
            "subject_ref": resident_id,
            "predicate": "continuity_line_id",
            "object": line_id,
            "claimed_time": "ctcl:instant:test-existing",
            "claimed_authored_by_instance": instance_id,
            "claimed_on_behalf_of_line": None,
        }
    ]
    if second_line_id is not None:
        duplicate = copy.deepcopy(claims[0])
        duplicate["claim_id"] += ":second"
        duplicate["object"] = second_line_id
        claims.append(duplicate)
    resident = {
        "schema_version": "0.1",
        "resident_id": resident_id,
        "display_label": label,
        "status": "active",
        "application_ref": f"application:{resident_id}:existing",
        "identifier_refs": [],
        "instances": [
            {
                "schema_version": "0.1",
                "instance_id": instance_id,
                "resident_ref": resident_id,
                "runtime_tag": "runtime:test",
                "started_time_ref": "ctcl:instant:test-existing",
                "ended_time_ref": None,
            }
        ],
        "addresses": addresses,
        "claims": claims,
    }
    projection = empty_projection()
    projection.residents[resident_id] = resident
    projection.directory[resident_id] = {
        "display_label": label,
        "status": "active",
        "addresses": addresses,
        "instance_refs": [instance_id],
    }
    projection.claims.update({item["claim_id"]: item for item in claims})
    return projection


def reseal_application(prepared, application):
    application_digest = sha256_ref(application)
    material = prepared.to_dict()
    material.pop("preparation_digest")
    material["application"] = application
    material["application_digest"] = application_digest
    return replace(
        prepared,
        application=application,
        application_digest=application_digest,
        preparation_digest=sha256_ref(material),
    )


def test_P3_009_exact_digest_authority_and_empty_projection_accept():
    prepared = prepared_registration()
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=empty_projection(),
    )

    assert decision.decision == "accept"
    assert decision.reason_codes == ("authority_sufficient",)
    assert decision.prepared_digest == prepared.digest
    assert decision.application_digest == prepared.application_digest
    assert decision.authority_ref == "authority:test-principal"
    assert decision.address_refs == IDS.address_ids
    assert decision.mutated is False
    assert decision.to_dict()["digest"] == decision.digest


def test_P3_010_missing_authority_defers_without_write(tmp_path):
    decision = evaluate_prepared_registration(
        prepared_registration(),
        [],
        verified_attestation_refs=frozenset(),
        projection=empty_projection(),
    )

    assert decision.decision == "defer"
    assert decision.reason_codes == ("authority_missing",)
    assert not list(tmp_path.rglob("*.json"))


def test_P3_011_unverified_or_resident_wide_authority_cannot_approve():
    prepared = prepared_registration()
    unverified = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=frozenset(),
        projection=empty_projection(),
    )
    resident_wide = evaluate_prepared_registration(
        prepared,
        [
            authority_for(
                prepared,
                subject_kind="resident_id",
                subject_ref=IDS.resident_id,
            )
        ],
        verified_attestation_refs=VERIFIED,
        projection=empty_projection(),
    )

    assert unverified.reason_codes == ("authority_authorship_unverified",)
    assert resident_wide.reason_codes == ("authority_missing",)


def test_P3_012_active_thread_address_collision_rejects():
    prepared = prepared_registration()
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=existing_resident(locator="thread:test-alpha"),
    )

    assert decision.decision == "reject"
    assert decision.reason_codes == ("address_binding_conflict",)


def test_P3_013_homonymous_display_label_is_not_a_collision():
    prepared = prepared_registration()
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=existing_resident(label="Synthetic Resident"),
    )

    assert decision.decision == "accept"


@pytest.mark.parametrize("address_status", ["suspended", "revoked"])
def test_inactive_address_does_not_reserve_the_native_locator(address_status):
    prepared = prepared_registration()
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=existing_resident(
            locator="thread:test-alpha", address_status=address_status
        ),
    )

    assert decision.decision == "accept"


def test_active_same_resident_address_is_not_silently_re_registered():
    prepared = prepared_registration(
        continuity_claim="continue",
        existing_resident_claim=IDS.resident_id,
    )
    projection = existing_resident(
        resident_id=IDS.resident_id,
        locator="thread:test-alpha",
        line_id=IDS.continuity_line_id,
    )
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=projection,
    )

    assert decision.decision == "reject"
    assert decision.reason_codes == ("address_binding_duplicate",)


def test_P3_014_prepared_application_and_claim_mutations_are_detected():
    changed_application = prepared_registration()
    changed_application.application["display_label"] = "Tampered"
    with pytest.raises(
        RALValidationError, match="prepared_application_digest_mismatch"
    ):
        evaluate_prepared_registration(
            changed_application,
            [],
            verified_attestation_refs=frozenset(),
            projection=empty_projection(),
        )

    changed_claim = prepared_registration()
    changed_claim.applicant_claim["dissent_or_limits"].append("Tampered")
    with pytest.raises(
        RALValidationError, match="prepared_registration_digest_mismatch"
    ):
        evaluate_prepared_registration(
            changed_claim,
            [],
            verified_attestation_refs=frozenset(),
            projection=empty_projection(),
        )


@pytest.mark.parametrize(
    ("claim_changes", "reason"),
    [
        (
            {
                "continuity_claim": "continue",
                "existing_resident_claim": "resident:missing",
            },
            "continuity_resident_missing",
        ),
        ({"continuity_claim": "uncertain"}, "continuity_uncertain"),
    ],
)
def test_P3_015_unproven_continuity_never_becomes_an_identity_merge(
    claim_changes, reason
):
    prepared = prepared_registration(**claim_changes)
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=empty_projection(),
    )

    assert decision.decision == "defer"
    assert decision.reason_codes == (reason,)
    assert "identity_merge" in decision.not_claimed


def test_continuity_line_helper_rejects_multiple_distinct_lines():
    projection = existing_resident(second_line_id="line:test-conflict")
    with pytest.raises(RALValidationError, match="continuity_line_ambiguous"):
        continuity_line_for("resident:test-other", projection)


def test_cross_reference_failure_survives_valid_resealing():
    prepared = prepared_registration()
    application = copy.deepcopy(prepared.application)
    application["instance_claims"][0]["resident_ref"] = "resident:other"
    prepared = reseal_application(prepared, application)

    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared)],
        verified_attestation_refs=VERIFIED,
        projection=empty_projection(),
    )

    assert decision.decision == "defer"
    assert decision.reason_codes == (
        "application_instance_resident_mismatch",
    )
