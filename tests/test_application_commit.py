import copy
import json
from pathlib import Path

import pytest

import sedb_ral.application as application_module
from sedb_ral.application import (
    commit_application,
    evaluate_application,
    project_authorities,
    revoke_authority,
)
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import read_verified_events

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads(
    (ROOT / "fixtures/application/authorized-zero-address.json").read_text(
        encoding="utf-8"
    )
)
CTCL = json.loads(
    (ROOT / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)
VERIFIED = frozenset({"attestation:neo:1"})


def decision(application=None, authority=None):
    return evaluate_application(
        application or FIXTURE["application"],
        [authority or FIXTURE["authorities"][0]],
        verified_attestation_refs=VERIFIED,
    )


def test_decision_does_not_write_files(tmp_path):
    result = decision()
    assert result.decision == "accept"
    assert not list(tmp_path.rglob("*.json"))


def test_commit_writes_submitted_accepted_and_registered_events(tmp_path):
    result = commit_application(
        tmp_path,
        FIXTURE["application"],
        decision(),
        FIXTURE["authorities"][0],
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
    )
    events = read_verified_events(tmp_path, result.chain_digest)
    assert [item["event_type"] for item in events] == [
        "authority.granted",
        "application.submitted",
        "application.accepted",
        "resident.registered",
    ]
    assert result.committed is True
    assert result.event_ids == tuple(item["event_id"] for item in events)
    grant, _, accepted, _ = events
    assert grant["payload"] == {
        "authority": FIXTURE["authorities"][0],
        "authority_digest": application_module.authority_digest(
            FIXTURE["authorities"][0]
        ),
        "authorship_attestation_ref": "attestation:neo:1",
        "authorship_verification_status": "verified",
    }
    assert accepted["payload"]["authority_id"] == "authority:test:1"
    assert accepted["payload"]["authority_digest"] == grant["payload"]["authority_digest"]
    assert accepted["payload"]["authority_grant_event_id"] == grant["event_id"]
    projected = project_authorities(events)
    assert projected == (FIXTURE["authorities"][0],)


def test_commit_revalidates_application_digest(tmp_path):
    original_decision = decision()
    changed = copy.deepcopy(FIXTURE["application"])
    changed["display_label"] = "Changed after decision"
    with pytest.raises(RALValidationError, match="application_digest_stale"):
        commit_application(
            tmp_path,
            changed,
            original_decision,
            FIXTURE["authorities"][0],
            CTCL,
            expected_head=None,
            verified_attestation_refs=VERIFIED,
        )
    assert not list(tmp_path.rglob("*.json"))


def test_commit_revalidates_authority_status(tmp_path):
    original_decision = decision()
    revoked = copy.deepcopy(FIXTURE["authorities"][0])
    revoked["status"] = "revoked"
    revoked["revoked_by_event"] = "evt_authority_revoked_test"
    with pytest.raises(RALValidationError, match="authority_revoked"):
        commit_application(
            tmp_path,
            FIXTURE["application"],
            original_decision,
            revoked,
            CTCL,
            expected_head=None,
            verified_attestation_refs=VERIFIED,
        )


def test_revocation_blocks_later_commit_without_deleting_grant(tmp_path):
    first = commit_application(
        tmp_path,
        FIXTURE["application"],
        decision(),
        FIXTURE["authorities"][0],
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
    )
    revocation = {
        "revocation_id": "revocation:test:1",
        "authority_id": "authority:test:1",
        "reason": "principal withdrew ordinary registration authority",
    }
    revoked = revoke_authority(
        tmp_path,
        FIXTURE["authorities"][0],
        revocation,
        CTCL,
        expected_head=first.chain_digest,
    )
    events = read_verified_events(tmp_path, revoked.chain_digest)
    projected = project_authorities(events)
    assert projected[0]["status"] == "revoked"
    assert projected[0]["revoked_by_event"] == revoked.event_id
    later = evaluate_application(
        FIXTURE["application"],
        projected,
        verified_attestation_refs=VERIFIED,
    )
    assert later.reason_codes == ("authority_revoked",)
    assert any(item["event_type"] == "authority.revoked" for item in events)
    assert any(item["event_type"] == "authority.granted" for item in events)


def test_identical_active_grant_is_reused_for_a_second_application(tmp_path):
    first = commit_application(
        tmp_path,
        FIXTURE["application"],
        decision(),
        FIXTURE["authorities"][0],
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
    )
    second_application = copy.deepcopy(FIXTURE["application"])
    second_application["application_id"] = "application:test:2"
    second_application["claims"][0]["claim_id"] = "claim:test:2"
    second = commit_application(
        tmp_path,
        second_application,
        decision(application=second_application),
        FIXTURE["authorities"][0],
        CTCL,
        expected_head=first.chain_digest,
        verified_attestation_refs=VERIFIED,
    )

    events = read_verified_events(tmp_path, second.chain_digest)
    grants = [item for item in events if item["event_type"] == "authority.granted"]
    assert len(grants) == 1
    assert second.authority_grant_event_id == grants[0]["event_id"]
    assert len(second.event_ids) == 3


def test_conflicting_same_id_grant_fails_before_any_followup_write(tmp_path):
    first = commit_application(
        tmp_path,
        FIXTURE["application"],
        decision(),
        FIXTURE["authorities"][0],
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
    )
    second_application = copy.deepcopy(FIXTURE["application"])
    second_application["application_id"] = "application:test:2"
    second_application["claims"][0]["claim_id"] = "claim:test:2"
    conflicting = copy.deepcopy(FIXTURE["authorities"][0])
    conflicting["scopes"].append("registry.application.inspect")

    with pytest.raises(RALValidationError, match="authority_grant_conflict"):
        commit_application(
            tmp_path,
            second_application,
            decision(application=second_application, authority=conflicting),
            conflicting,
            CTCL,
            expected_head=first.chain_digest,
            verified_attestation_refs=VERIFIED,
        )

    assert len(read_verified_events(tmp_path, first.chain_digest)) == 4


def test_changed_grant_snapshot_or_digest_fails_projection():
    authority = copy.deepcopy(FIXTURE["authorities"][0])
    event = {
        "ledger_seq": 1,
        "event_id": "evt_authority_granted_test",
        "event_type": "authority.granted",
        "payload": {
            "authority": authority,
            "authority_digest": application_module.authority_digest(authority),
            "authorship_attestation_ref": authority["authorship_attestation_ref"],
            "authorship_verification_status": "verified",
        },
    }
    event["payload"]["authority"]["principal_ref"] = "principal:other"

    with pytest.raises(RALValidationError, match="authority_grant_digest_mismatch"):
        project_authorities([event])


def test_unverified_or_absent_grant_cannot_project_authority():
    authority = FIXTURE["authorities"][0]
    unverified = {
        "ledger_seq": 1,
        "event_id": "evt_authority_granted_test",
        "event_type": "authority.granted",
        "payload": {
            "authority": authority,
            "authority_digest": application_module.authority_digest(authority),
            "authorship_attestation_ref": authority["authorship_attestation_ref"],
            "authorship_verification_status": "unverified",
        },
    }
    with pytest.raises(RALValidationError, match="authority_authorship_unverified"):
        project_authorities([unverified])

    revoked_without_grant = {
        "ledger_seq": 1,
        "event_id": "evt_authority_revoked_test",
        "event_type": "authority.revoked",
        "payload": {
            "authority_id": authority["authority_id"],
            "authority_digest": application_module.authority_digest(authority),
            "authority_grant_event_id": "evt_authority_granted_missing",
            "revocation": {
                "revocation_id": "revocation:test:1",
                "authority_id": authority["authority_id"],
                "reason": "withdrawn",
            },
        },
    }
    with pytest.raises(RALValidationError, match="authority_grant_missing"):
        project_authorities([revoked_without_grant])


def test_wrong_external_head_refuses_followup_append(tmp_path):
    first = commit_application(
        tmp_path,
        FIXTURE["application"],
        decision(),
        FIXTURE["authorities"][0],
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
    )
    with pytest.raises(RALValidationError, match="external_anchor_mismatch"):
        revoke_authority(
            tmp_path,
            FIXTURE["authorities"][0],
            {
                "revocation_id": "revocation:test:1",
                "authority_id": "authority:test:1",
                "reason": "withdrawn",
            },
            CTCL,
            expected_head="sha256:sedb-ral-chain-v1:" + "0" * 64,
        )
    assert first.chain_digest != "sha256:sedb-ral-chain-v1:" + "0" * 64
