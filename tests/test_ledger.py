import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import LedgerStatus, append_event, verify_ledger

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


def append_genesis(root: Path, value=None, receipt=None):
    return append_event(
        root,
        value or draft("evt_001"),
        receipt or CTCL,
        expected_previous_chain_digest=None,
    )


def append_after(root: Path, value, previous):
    return append_event(
        root,
        value,
        CTCL,
        expected_previous_chain_digest=previous.chain_digest,
    )


def test_append_and_verify_two_events(tmp_path):
    first = append_genesis(tmp_path)
    second = append_after(
        tmp_path, draft("evt_002", ("evt_001",)), first
    )
    result = verify_ledger(
        tmp_path,
        expected_final_chain_digest=second.chain_digest,
    )
    assert result.valid is True
    assert result.status is LedgerStatus.CHECKPOINT_VERIFIED
    assert result.event_count == 2
    assert result.final_chain_digest == second.chain_digest
    assert first.ledger_seq == 1


def test_empty_ledger_is_not_reported_as_verified(tmp_path):
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert result.status is LedgerStatus.EMPTY
    assert result.error_codes == ()


def test_external_chain_expectation_detects_a_fully_wiped_ledger(tmp_path):
    receipt = append_genesis(tmp_path)
    receipt.event_path.unlink()
    receipt.anchor_path.unlink()
    result = verify_ledger(
        tmp_path,
        expected_final_chain_digest=receipt.chain_digest,
    )
    assert result.valid is False
    assert result.status is LedgerStatus.INVALID
    assert "external_anchor_mismatch" in result.error_codes


def test_external_chain_expectation_detects_paired_tail_rollback(tmp_path):
    first = append_genesis(tmp_path)
    second = append_after(
        tmp_path, draft("evt_002", ("evt_001",)), first
    )
    second.event_path.unlink()
    second.anchor_path.unlink()
    result = verify_ledger(
        tmp_path,
        expected_final_chain_digest=second.chain_digest,
    )
    assert result.valid is False
    assert result.status is LedgerStatus.INVALID
    assert "external_anchor_mismatch" in result.error_codes


def test_nonempty_ledger_without_checkpoint_is_only_internally_consistent(
    tmp_path,
):
    append_genesis(tmp_path)
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert result.status is LedgerStatus.INTERNALLY_CONSISTENT
    assert result.error_codes == ()


def test_nonempty_append_requires_the_expected_previous_head(tmp_path):
    append_genesis(tmp_path)
    with pytest.raises(RALValidationError, match="genesis_conflicts"):
        append_event(
            tmp_path,
            draft("evt_002", ("evt_001",)),
            CTCL,
            expected_previous_chain_digest=None,
        )


def test_append_with_external_head_detects_a_fully_wiped_ledger(tmp_path):
    first = append_genesis(tmp_path)
    first.event_path.unlink()
    first.anchor_path.unlink()
    with pytest.raises(RALValidationError, match="ledger_invalid"):
        append_event(
            tmp_path,
            draft("evt_002", ("evt_001",)),
            CTCL,
            expected_previous_chain_digest=first.chain_digest,
        )


def test_genesis_digest_matches_the_pinned_chain_algorithm(tmp_path):
    receipt = append_genesis(tmp_path)
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
    receipt = append_genesis(tmp_path)
    for path in (receipt.event_path, receipt.anchor_path):
        raw = path.read_bytes()
        assert raw == canonical_bytes(json.loads(raw))
        assert not raw.endswith(b"\n")


def test_mutation_turns_verification_red(tmp_path):
    receipt = append_genesis(tmp_path)
    value = read_json(receipt.event_path)
    value["payload"]["identifier_id"] = "id:mutated"
    receipt.event_path.write_text(json.dumps(value), encoding="utf-8")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "record_digest_mismatch" in result.error_codes


def test_deletion_turns_anchor_red(tmp_path):
    first = append_genesis(tmp_path)
    append_after(tmp_path, draft("evt_002", ("evt_001",)), first)
    first.event_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "sequence_gap" in result.error_codes


def test_duplicate_event_id_is_refused(tmp_path):
    first = append_genesis(tmp_path)
    with pytest.raises(RALValidationError, match="duplicate_event_id"):
        append_event(
            tmp_path,
            draft("evt_001"),
            CTCL,
            expected_previous_chain_digest=first.chain_digest,
        )


def test_reading_cannot_anchor_recorded_time(tmp_path):
    reading = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/ctcl/reading.json"
        ).read_text(encoding="utf-8")
    )
    with pytest.raises(RALValidationError, match="registered_anchor_required"):
        append_event(
            tmp_path,
            draft("evt_001"),
            reading,
            expected_previous_chain_digest=None,
        )


def test_recorded_time_ref_must_match_anchor(tmp_path):
    value = draft("evt_001")
    value["recorded_time_ref"] = (
        "ctcl:instant:00000000-0000-0000-0000-000000000000"
    )
    with pytest.raises(RALValidationError, match="recorded_time_ref_mismatch"):
        append_event(
            tmp_path,
            value,
            CTCL,
            expected_previous_chain_digest=None,
        )


def test_recorded_time_value_must_match_anchor(tmp_path):
    value = draft("evt_001")
    value["recorded_time"] = "2026-08-23T08:09:40.165Z"
    with pytest.raises(RALValidationError, match="recorded_time_mismatch"):
        append_event(
            tmp_path,
            value,
            CTCL,
            expected_previous_chain_digest=None,
        )


def test_missing_causal_parent_is_refused(tmp_path):
    with pytest.raises(RALValidationError, match="causal_parent_missing"):
        append_event(
            tmp_path,
            draft("evt_001", ("evt_missing",)),
            CTCL,
            expected_previous_chain_digest=None,
        )


def test_event_without_anchor_is_detected(tmp_path):
    receipt = append_genesis(tmp_path)
    receipt.anchor_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchor_missing" in result.error_codes


def test_filename_sequence_disagreement_is_detected(tmp_path):
    receipt = append_genesis(tmp_path)
    wrong = receipt.event_path.with_name(
        "00000000000000000002-evt_001.json"
    )
    receipt.event_path.rename(wrong)
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "filename_sequence_mismatch" in result.error_codes


def test_deleted_tail_with_anchor_is_detected(tmp_path):
    receipt = append_genesis(tmp_path)
    receipt.event_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchored_event_missing" in result.error_codes


def test_anchor_mutation_is_detected(tmp_path):
    receipt = append_genesis(tmp_path)
    value = read_json(receipt.anchor_path)
    value["final_chain_digest"] = (
        "sha256:sedb-ral-chain-v1:" + "0" * 64
    )
    receipt.anchor_path.write_text(json.dumps(value), encoding="utf-8")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchor_digest_mismatch" in result.error_codes


def test_append_refuses_an_already_corrupt_ledger(tmp_path):
    receipt = append_genesis(tmp_path)
    value = read_json(receipt.event_path)
    value["payload"]["identifier_id"] = "id:mutated"
    receipt.event_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RALValidationError, match="ledger_invalid"):
        append_event(
            tmp_path,
            draft("evt_002", ("evt_001",)),
            CTCL,
            expected_previous_chain_digest=receipt.chain_digest,
        )


def test_hard_link_failure_is_a_typed_error(tmp_path, monkeypatch):
    def fail_link(source, destination):
        raise OSError("hard links unavailable")

    monkeypatch.setattr("sedb_ral.ledger.os.link", fail_link)
    with pytest.raises(RALValidationError, match="immutable_publish_failed"):
        append_genesis(tmp_path)
    assert not list((tmp_path / "events").rglob("*.json"))


@pytest.mark.parametrize("node", ["events", "anchors"])
def test_storage_node_must_be_a_directory(tmp_path, node):
    (tmp_path / node).write_text("not a directory", encoding="utf-8")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert result.status is LedgerStatus.INVALID
    assert "storage_layout_invalid" in result.error_codes


def test_symlinked_event_storage_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / "events").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert result.status is LedgerStatus.INVALID
    assert "storage_layout_invalid" in result.error_codes


def test_detected_reparse_storage_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "events").mkdir()
    monkeypatch.setattr(
        "sedb_ral.ledger._is_reparse_point",
        lambda path: path.name == "events",
        raising=False,
    )
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert result.status is LedgerStatus.INVALID
    assert "storage_layout_invalid" in result.error_codes


def test_concurrent_genesis_attempts_publish_one_complete_event(tmp_path):
    def attempt(index):
        try:
            return append_event(
                tmp_path,
                draft(f"evt_{index:03d}"),
                CTCL,
                expected_previous_chain_digest=None,
            )
        except RALValidationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(attempt, range(1, 41)))

    receipts = [item for item in outcomes if not isinstance(item, str)]
    errors = [item for item in outcomes if isinstance(item, str)]
    assert len(receipts) == 1
    assert set(errors) <= {
        "append_in_progress",
        "genesis_conflicts_with_existing_ledger",
    }
    result = verify_ledger(
        tmp_path,
        expected_final_chain_digest=receipts[0].chain_digest,
    )
    assert result.valid is True
    assert result.event_count == 1
