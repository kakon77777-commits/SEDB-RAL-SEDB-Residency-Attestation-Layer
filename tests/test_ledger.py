import json
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import append_event, verify_ledger

CTCL = json.loads(
    (
        Path(__file__).parents[1]
        / "fixtures/ctcl/registered-anchor.json"
    ).read_text(encoding="utf-8")
)


def draft(event_id: str, parent_ids=()):
    return {
        "schema_version": "0.1",
        "event_id": event_id,
        "ledger_id": "ledger:test",
        "event_type": "identifier.observed",
        "causal_parent_ids": list(parent_ids),
        "recorded_time_ref": (
            "ctcl:instant:5a76bd1b-2db2-463b-b2ad-0b1307102710"
        ),
        "recorded_time": "2026-08-23T08:09:39.165Z",
        "payload": {"identifier_id": "id:test"},
    }


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_append_and_verify_two_events(tmp_path):
    first = append_event(tmp_path, draft("evt_001"), CTCL)
    second = append_event(tmp_path, draft("evt_002", ("evt_001",)), CTCL)
    result = verify_ledger(tmp_path)
    assert result.valid is True
    assert result.event_count == 2
    assert result.final_chain_digest == second.chain_digest
    assert first.ledger_seq == 1


def test_genesis_digest_matches_the_pinned_chain_algorithm(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    assert receipt.record_digest == (
        "sha256:"
        "2e67caf7cdd3cebf0956a0062b31665e"
        "5ec5ae35269838299889c6c0dd584ebb"
    )
    assert receipt.chain_digest == (
        "sha256:sedb-ral-chain-v1:"
        "d7a208bcdf8fa65e57a530af4630076f"
        "8c2a164e4e9060d924eb80226dea662b"
    )


def test_published_event_and_anchor_are_canonical_without_newline(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    for path in (receipt.event_path, receipt.anchor_path):
        raw = path.read_bytes()
        assert raw == canonical_bytes(json.loads(raw))
        assert not raw.endswith(b"\n")


def test_mutation_turns_verification_red(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    value = read_json(receipt.event_path)
    value["payload"]["identifier_id"] = "id:mutated"
    receipt.event_path.write_text(json.dumps(value), encoding="utf-8")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "record_digest_mismatch" in result.error_codes


def test_deletion_turns_anchor_red(tmp_path):
    first = append_event(tmp_path, draft("evt_001"), CTCL)
    append_event(tmp_path, draft("evt_002", ("evt_001",)), CTCL)
    first.event_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "sequence_gap" in result.error_codes


def test_duplicate_event_id_is_refused(tmp_path):
    append_event(tmp_path, draft("evt_001"), CTCL)
    with pytest.raises(RALValidationError, match="duplicate_event_id"):
        append_event(tmp_path, draft("evt_001"), CTCL)


def test_reading_cannot_anchor_recorded_time(tmp_path):
    reading = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/ctcl/reading.json"
        ).read_text(encoding="utf-8")
    )
    with pytest.raises(RALValidationError, match="registered_anchor_required"):
        append_event(tmp_path, draft("evt_001"), reading)


def test_recorded_time_ref_must_match_anchor(tmp_path):
    value = draft("evt_001")
    value["recorded_time_ref"] = (
        "ctcl:instant:00000000-0000-0000-0000-000000000000"
    )
    with pytest.raises(RALValidationError, match="recorded_time_ref_mismatch"):
        append_event(tmp_path, value, CTCL)


def test_recorded_time_value_must_match_anchor(tmp_path):
    value = draft("evt_001")
    value["recorded_time"] = "2026-08-23T08:09:40.165Z"
    with pytest.raises(RALValidationError, match="recorded_time_mismatch"):
        append_event(tmp_path, value, CTCL)


def test_missing_causal_parent_is_refused(tmp_path):
    with pytest.raises(RALValidationError, match="causal_parent_missing"):
        append_event(tmp_path, draft("evt_001", ("evt_missing",)), CTCL)


def test_event_without_anchor_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    receipt.anchor_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchor_missing" in result.error_codes


def test_filename_sequence_disagreement_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    wrong = receipt.event_path.with_name(
        "00000000000000000002-evt_001.json"
    )
    receipt.event_path.rename(wrong)
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "filename_sequence_mismatch" in result.error_codes


def test_deleted_tail_with_anchor_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    receipt.event_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchored_event_missing" in result.error_codes


def test_anchor_mutation_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    value = read_json(receipt.anchor_path)
    value["final_chain_digest"] = (
        "sha256:sedb-ral-chain-v1:" + "0" * 64
    )
    receipt.anchor_path.write_text(json.dumps(value), encoding="utf-8")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchor_digest_mismatch" in result.error_codes


def test_append_refuses_an_already_corrupt_ledger(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    value = read_json(receipt.event_path)
    value["payload"]["identifier_id"] = "id:mutated"
    receipt.event_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RALValidationError, match="ledger_invalid"):
        append_event(tmp_path, draft("evt_002", ("evt_001",)), CTCL)
