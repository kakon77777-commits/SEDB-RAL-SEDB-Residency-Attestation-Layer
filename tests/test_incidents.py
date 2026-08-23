import hashlib
import json
from pathlib import Path

from sedb_ral.canonical import canonical_bytes
from sedb_ral.incidents import (
    CORPUS_SOURCE_SHA256,
    incident_counts,
    load_incidents,
    negative_gate_cases,
    render_incidents,
    validate_required_negative_cases,
)

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "corpus/incidents.jsonl"


def test_corpus_bytes_match_approved_source_hash_and_canonical_lines():
    assert hashlib.sha256(CORPUS.read_bytes()).hexdigest().upper() == (
        CORPUS_SOURCE_SHA256
    )
    for line in CORPUS.read_bytes().splitlines():
        row = json.loads(line)
        assert line == canonical_bytes(row)


def test_counts_derive_from_rows():
    rows = load_incidents(CORPUS)
    assert len(rows) == 29
    assert incident_counts(rows)["class"] == {
        "A": 8,
        "B": 4,
        "C": 10,
        "D": 3,
        "E": 2,
        "F": 2,
    }
    assert incident_counts(rows)["origin_strength"] == {
        "own_execution": 17,
        "peer_assertion": 7,
        "peer_assertion_verified": 2,
        "peer_transcript": 3,
    }


def test_all_imported_rows_keep_retrospective_time_boundary():
    rows = load_incidents(CORPUS)
    assert all(row["retro_stamped"] is True for row in rows)
    assert all(row["temporal_capture_mode"] == "retrospective" for row in rows)
    assert all(row["observed_time_ref"] is None for row in rows)


def test_incidents_3_24_25_feed_negative_gates():
    cases = negative_gate_cases(load_incidents(CORPUS))
    assert set(cases) == {3, 24, 25}
    assert cases[3].gate == "resident_identifier_discrimination"
    assert cases[24].gate == "adapter_route_readiness"
    assert cases[25].gate == "address_failure_classification"
    assert validate_required_negative_cases(cases) == ()


def test_missing_required_incident_turns_consumer_red(tmp_path):
    rows = [row for row in load_incidents(CORPUS) if row["id"] != 24]
    copy = tmp_path / "incidents.jsonl"
    copy.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
    loaded = load_incidents(copy)
    assert len(loaded) == 28
    assert validate_required_negative_cases(negative_gate_cases(loaded)) == (
        "required_negative_incident_missing:24",
    )


def test_generated_markdown_matches_jsonl():
    assert (ROOT / "corpus/incidents.md").read_text(encoding="utf-8") == (
        render_incidents(load_incidents(CORPUS))
    )
