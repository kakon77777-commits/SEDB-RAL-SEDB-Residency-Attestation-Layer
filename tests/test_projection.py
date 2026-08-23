import json
import copy
from pathlib import Path

import pytest

from sedb_ral.application import commit_application, evaluate_application
from sedb_ral.ledger import read_verified_events
from sedb_ral.projection import (
    compare_projection_bytes,
    project_events,
    write_projection,
)
from sedb_ral.errors import RALValidationError

ROOT = Path(__file__).parents[1]
APPLICATION_FIXTURE = json.loads(
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


def committed_events(tmp_path):
    application = APPLICATION_FIXTURE["application"]
    authority = APPLICATION_FIXTURE["authorities"][0]
    decision = evaluate_application(
        application,
        [authority],
        verified_attestation_refs=VERIFIED,
    )
    receipt = commit_application(
        tmp_path,
        application,
        decision,
        authority,
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
    )
    return read_verified_events(tmp_path, receipt.chain_digest)


def test_projection_rebuilds_application_resident_and_directory(tmp_path):
    projection = project_events(committed_events(tmp_path / "ledger"))
    assert projection.applications["application:test:1"]["status"] == "accepted"
    assert projection.residents["resident:test"]["display_label"] == "Test Resident"
    assert projection.directory["resident:test"]["addresses"] == []
    assert projection.unapplied_event_ids == ()
    assert projection.unapplied_reasons == {}
    registered = next(
        item
        for item in committed_events(tmp_path / "second-ledger")
        if item["event_type"] == "resident.registered"
    )
    assert projection.resident_source_event_ids == {
        "resident:test": registered["event_id"]
    }


def test_two_rebuilds_are_byte_identical(tmp_path):
    projection = project_events(committed_events(tmp_path / "ledger"))
    first = write_projection(projection, tmp_path / "a")
    second = write_projection(projection, tmp_path / "b")
    assert compare_projection_bytes(first, second) == ()
    assert [path.relative_to(tmp_path / "a").as_posix() for path in first] == [
        path.relative_to(tmp_path / "b").as_posix() for path in second
    ]


def test_correction_changes_projection_without_deleting_target_event(tmp_path):
    events = list(committed_events(tmp_path / "ledger"))
    target = events[-1]
    replacement = copy.deepcopy(APPLICATION_FIXTURE["application"]["claims"][0])
    replacement["claim_id"] = "claim:test:2"
    replacement["object"] = "Corrected"
    events.append(
        {
            "ledger_seq": 5,
            "event_id": "evt_claim_replacement",
            "event_type": "claim.recorded",
            "payload": {"claim": replacement},
        }
    )
    events.append(
        {
            "ledger_seq": 6,
            "event_id": "evt_correction_display_label",
            "event_type": "record.corrected",
            "payload": {
                "correction": {
                    "schema_version": "0.1",
                    "correction_id": "correction:test:1",
                    "target_event_id": target["event_id"],
                    "action": "correct",
                    "replacement_ref": "claim:test:2",
                    "reason": "correct display label",
                },
                "target_kind": "resident",
                "target_ref": "resident:test",
                "changes": {"display_label": "Corrected"},
            },
        }
    )
    projection = project_events(events)
    assert projection.residents["resident:test"]["display_label"] == "Corrected"
    assert projection.applied_corrections == ("correction:test:1",)
    assert target["event_id"] in projection.source_event_ids


def correction_event(events, *, action="correct"):
    target = next(
        item for item in events if item["event_type"] == "resident.registered"
    )
    replacement = copy.deepcopy(APPLICATION_FIXTURE["application"]["claims"][0])
    replacement["claim_id"] = "claim:test:2"
    replacement["object"] = "Corrected"
    values = list(events)
    values.append(
        {
            "ledger_seq": len(values) + 1,
            "event_id": "evt_claim_replacement",
            "event_type": "claim.recorded",
            "payload": {"claim": replacement},
        }
    )
    payload = {
        "correction": {
            "schema_version": "0.1",
            "correction_id": "correction:test:1",
            "target_event_id": target["event_id"],
            "action": action,
            "replacement_ref": "claim:test:2" if action == "correct" else None,
            "reason": "projection correction control",
        },
        "target_kind": "resident",
        "target_ref": "resident:test",
    }
    if action == "correct":
        payload["changes"] = {"display_label": "Corrected"}
    values.append(
        {
            "ledger_seq": len(values) + 1,
            "event_id": "evt_correction_control",
            "event_type": "record.corrected",
            "payload": payload,
        }
    )
    return values


def test_wrong_target_event_and_entity_remain_unapplied_with_stable_reasons(tmp_path):
    events = list(committed_events(tmp_path / "ledger"))
    wrong_event = correction_event(events)
    accepted = next(
        item for item in events if item["event_type"] == "application.accepted"
    )
    wrong_event[-1]["payload"]["correction"]["target_event_id"] = accepted[
        "event_id"
    ]
    projection = project_events(wrong_event)
    assert projection.residents["resident:test"]["display_label"] == "Test Resident"
    assert projection.unapplied_reasons["evt_correction_control"] == (
        "correction_target_event_mismatch"
    )

    wrong_entity = correction_event(events)
    wrong_entity[-1]["payload"]["target_ref"] = "resident:other"
    projection = project_events(wrong_entity)
    assert projection.unapplied_reasons["evt_correction_control"] == (
        "correction_target_entity_mismatch"
    )


def test_wrong_action_payload_never_mutates_display_label(tmp_path):
    events = correction_event(
        list(committed_events(tmp_path / "ledger")), action="withdraw"
    )
    events[-1]["payload"]["changes"] = {"display_label": "Wrong path"}

    projection = project_events(events)

    assert projection.residents["resident:test"]["display_label"] == "Test Resident"
    assert projection.unapplied_reasons["evt_correction_control"] == (
        "correction_payload_unsupported"
    )


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("withdraw", "withdrawn"), ("tombstone", "tombstoned")],
)
def test_withdraw_and_tombstone_use_status_branch_not_label_path(
    tmp_path, action, expected_status
):
    events = correction_event(
        list(committed_events(tmp_path / "ledger")), action=action
    )

    projection = project_events(events)

    resident = projection.residents["resident:test"]
    assert resident["display_label"] == "Test Resident"
    assert resident["status"] == expected_status
    assert projection.applied_corrections == ("correction:test:1",)


def test_missing_replacement_provenance_remains_unapplied(tmp_path):
    events = correction_event(list(committed_events(tmp_path / "ledger")))
    events.pop(-2)
    events[-1]["ledger_seq"] -= 1

    projection = project_events(events)

    assert projection.unapplied_reasons["evt_correction_control"] == (
        "correction_replacement_missing"
    )


def test_acceptance_without_matching_prior_grant_cannot_register_resident(tmp_path):
    events = [
        item
        for item in committed_events(tmp_path / "ledger")
        if item["event_type"] != "authority.granted"
    ]

    projection = project_events(events)

    assert projection.applications["application:test:1"]["status"] == "submitted"
    assert projection.residents == {}
    assert projection.unapplied_reasons == {
        "evt_application_accepted_" + application_suffix(): "application_authority_grant_missing",
        "evt_resident_registered_" + application_suffix(): "resident_registration_not_authorized",
    }


def application_suffix():
    from sedb_ral.application import application_digest

    return application_digest(APPLICATION_FIXTURE["application"]).rsplit(":", 1)[-1][
        :16
    ]


def test_unknown_event_is_preserved_as_unapplied(tmp_path):
    events = list(committed_events(tmp_path / "ledger"))
    events.append(
        {
            "ledger_seq": 4,
            "event_id": "evt_unknown_test",
            "event_type": "future.event",
            "payload": {},
        }
    )
    projection = project_events(events)
    assert projection.unapplied_event_ids == ("evt_unknown_test",)


def test_projection_mutation_turns_byte_gate_red(tmp_path):
    projection = project_events(committed_events(tmp_path / "ledger"))
    first = write_projection(projection, tmp_path / "a")
    second = write_projection(projection, tmp_path / "b")
    second[0].write_bytes(second[0].read_bytes() + b" ")
    assert "projection_mismatch" in compare_projection_bytes(first, second)


def test_in_place_rebuild_rejects_nonempty_output_instead_of_leaving_stale_files(
    tmp_path,
):
    projection = project_events(committed_events(tmp_path / "ledger"))
    output = tmp_path / "output"
    first = write_projection(projection, output)

    empty_projection = project_events(())
    with pytest.raises(RALValidationError, match="projection_output_not_empty"):
        write_projection(empty_projection, output)

    assert all(path.exists() for path in first)
