import copy

import pytest
from test_phase3_registrar_plan import CTCL, VERIFIED, build_plan
from test_phase3_registration_admission import authority_for
from test_phase3_registration_prepare import (
    valid_claim,
    valid_host_observation,
)

from sedb_ral.application import application_digest
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import read_verified_events, verify_ledger
from sedb_ral.projection import project_events
from sedb_ral.registrar import (
    build_admission_plan,
    commit_admission_plan,
    find_committed_registration,
    inspect_registration_prefix,
)
from sedb_ral.registration import RegistrationIds, prepare_registration
from sedb_ral.registration_admission import evaluate_prepared_registration


def committed_registration(tmp_path):
    canonical, prepared, authority, decision, plan = build_plan(tmp_path)
    receipt = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )
    return canonical, prepared, authority, decision, plan, receipt


def test_P3_020_identical_retry_returns_existing_receipt(tmp_path):
    canonical, prepared, authority, decision, plan, first = (
        committed_registration(tmp_path)
    )

    second = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )

    assert second.final_head == first.final_head
    assert second.event_ids == first.event_ids
    assert second.prepared_digest == prepared.digest
    assert second.committed is False
    assert second.idempotent is True


def test_find_committed_registration_reconstructs_phase3_receipt(tmp_path):
    canonical, prepared, _, _, plan, receipt = committed_registration(
        tmp_path
    )
    events = read_verified_events(canonical, receipt.final_head)

    found = find_committed_registration(events, prepared.application_digest)

    assert found is not None
    assert found.prepared_digest == prepared.digest
    assert found.source_head == plan.source_head
    assert found.final_head == receipt.final_head
    assert found.event_ids == plan.candidate_event_ids
    assert found.committed is False
    assert found.idempotent is True
    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "complete"
    )


def _trim_to_valid_prefix(canonical, keep):
    event_paths = sorted((canonical / "events").rglob("*.json"))
    anchor_paths = sorted((canonical / "anchors").glob("*.json"))
    for path in event_paths[keep:]:
        path.unlink()
    for path in anchor_paths[keep:]:
        path.unlink()


def test_P3_021_valid_partial_prefix_is_detected_not_resumed_implicitly(
    tmp_path,
):
    canonical, prepared, authority, decision, plan, _ = (
        committed_registration(tmp_path)
    )
    _trim_to_valid_prefix(canonical, keep=2)
    partial = verify_ledger(canonical)
    assert partial.error_codes == ()
    events = read_verified_events(canonical, partial.final_chain_digest)
    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "partial"
    )
    before = {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in canonical.rglob("*.json")
    }

    with pytest.raises(
        RALValidationError, match="registrar_partial_transaction"
    ):
        commit_admission_plan(
            canonical,
            plan,
            prepared,
            decision,
            authority,
            CTCL,
            verified_attestation_refs=VERIFIED,
        )

    assert before == {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in canonical.rglob("*.json")
    }


def test_same_application_id_with_different_digest_is_conflicting(tmp_path):
    canonical, prepared, _, _, _, receipt = committed_registration(tmp_path)
    events = list(read_verified_events(canonical, receipt.final_head))
    other = copy.deepcopy(events[1])
    other["ledger_seq"] = len(events) + 1
    other["event_id"] = "evt_application_submitted_conflicting"
    other["payload"]["application"]["display_label"] = "Different"
    other_digest = application_digest(other["payload"]["application"])
    other["payload"]["application_digest"] = other_digest
    other["payload"]["decision"]["application_digest"] = other_digest
    events.append(other)

    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "conflicting"
    )


def test_same_address_id_with_different_locator_is_conflicting(tmp_path):
    canonical, prepared, _, _, _, receipt = committed_registration(tmp_path)
    events = list(read_verified_events(canonical, receipt.final_head))
    other = copy.deepcopy(events[-1])
    other["ledger_seq"] = len(events) + 1
    other["event_id"] = "evt_resident_registered_conflicting_address"
    other["payload"]["resident"]["resident_id"] = "resident:other"
    other["payload"]["resident"]["application_ref"] = "application:other"
    other["payload"]["addresses"][0]["target_ref"] = "resident:other"
    other["payload"]["addresses"][0]["locator"] = "thread:other"
    events.append(other)

    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "conflicting"
    )


def test_accepted_application_without_registered_resident_is_partial(tmp_path):
    canonical, prepared, _, _, _, receipt = committed_registration(tmp_path)
    events = read_verified_events(canonical, receipt.final_head)[:-1]

    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "partial"
    )


def test_registered_resident_with_mismatched_authority_grant_conflicts(
    tmp_path,
):
    canonical, prepared, _, _, _, receipt = committed_registration(tmp_path)
    events = list(read_verified_events(canonical, receipt.final_head))
    events[-2]["payload"]["authority_grant_event_id"] = "evt_grant:other"

    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "conflicting"
    )


def test_revocation_inside_registration_prefix_conflicts(tmp_path):
    canonical, prepared, _, _, _, receipt = committed_registration(tmp_path)
    events = list(read_verified_events(canonical, receipt.final_head))
    grant = events[0]
    accepted = events[-2]
    revocation = {
        "ledger_seq": 2,
        "event_id": "evt_authority_revoked_during_registration",
        "event_type": "authority.revoked",
        "payload": {
            "authority_id": accepted["payload"]["authority_id"],
            "authority_digest": accepted["payload"]["authority_digest"],
            "authority_grant_event_id": grant["event_id"],
            "revocation": {
                "revocation_id": "revocation:test-registration",
                "authority_id": accepted["payload"]["authority_id"],
                "reason": "synthetic recovery control",
            },
        },
    }
    for event in events[1:]:
        event["ledger_seq"] += 1
    events.insert(1, revocation)

    assert (
        inspect_registration_prefix(events, prepared.application_digest)
        == "conflicting"
    )


def test_nonempty_expected_head_admits_and_retries_second_applicant(tmp_path):
    canonical, _, _, _, _, first = committed_registration(tmp_path)
    second_ids = RegistrationIds(
        prepared_id="prepared:2f2635d4",
        application_id="application:aab9a46c",
        resident_id="resident:62c1b027",
        instance_id="instance:67c29194",
        continuity_line_id="line:5dc9745a",
        address_ids=("address:codex-thread:e41bcb77",),
        claim_ids=(
            "claim:display:0eb29057",
            "claim:role:092bdb6d",
            "claim:line:5fc7fa42",
        ),
    )
    claim = valid_claim(
        desired_display_label="Second Synthetic Resident",
        desired_addresses=[
            {
                "namespace": "codex_thread",
                "identifier_kind": "codex_thread",
                "locator": "thread:test-beta",
            }
        ],
    )
    host = valid_host_observation(
        observation_id="observation:test-beta",
        native_thread_id="thread:test-beta",
        native_turn_id="turn:test-beta",
        applicant_item_ref="item:test-beta",
    )
    prepared = prepare_registration(claim, host, second_ids)
    authority = authority_for(
        prepared, authority_id="authority:test-principal-second"
    )
    source_events = read_verified_events(canonical, first.final_head)
    decision = evaluate_prepared_registration(
        prepared,
        [authority],
        verified_attestation_refs=VERIFIED,
        projection=project_events(source_events),
    )
    plan = build_admission_plan(
        canonical,
        prepared,
        decision,
        authority,
        CTCL,
        expected_head=first.final_head,
        verified_attestation_refs=VERIFIED,
        staging_parent=tmp_path / "second-staging",
    )

    admitted = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )
    retried = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )

    assert admitted.source_head == first.final_head
    assert admitted.committed is True
    assert retried.final_head == admitted.final_head
    assert retried.idempotent is True
    final_projection = project_events(
        read_verified_events(canonical, admitted.final_head)
    )
    assert set(final_projection.residents) == {
        "resident:75c9559e",
        second_ids.resident_id,
    }
