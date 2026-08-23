import json
from pathlib import Path

from sedb_ral.application import commit_application, evaluate_application
from sedb_ral.ledger import read_verified_events
from sedb_ral.projection import (
    compare_projection_bytes,
    project_events,
    write_projection,
)

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
    events.append(
        {
            "ledger_seq": 4,
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
