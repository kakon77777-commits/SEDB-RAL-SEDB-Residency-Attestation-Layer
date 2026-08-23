import copy
import json
from pathlib import Path

import pytest

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
        "application.submitted",
        "application.accepted",
        "resident.registered",
    ]
    assert result.committed is True
    assert result.event_ids == tuple(item["event_id"] for item in events)


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
