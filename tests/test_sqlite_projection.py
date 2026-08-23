import json
import sqlite3
from pathlib import Path

from sedb_ral.application import commit_application, evaluate_application
from sedb_ral.ledger import read_verified_events
from sedb_ral.sqlite_projection import rebuild_sqlite

ROOT = Path(__file__).parents[1]
APPLICATION = json.loads(
    (ROOT / "fixtures/application/authorized-zero-address.json").read_text(
        encoding="utf-8"
    )
)
CTCL = json.loads(
    (ROOT / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)


def committed_events(tmp_path: Path) -> tuple[dict[str, object], ...]:
    decision = evaluate_application(
        APPLICATION["application"],
        APPLICATION["authorities"],
        verified_attestation_refs=frozenset({"attestation:neo:1"}),
    )
    receipt = commit_application(
        tmp_path,
        APPLICATION["application"],
        decision,
        APPLICATION["authorities"][0],
        CTCL,
        expected_head=None,
        verified_attestation_refs=frozenset({"attestation:neo:1"}),
    )
    return read_verified_events(tmp_path, receipt.chain_digest)


def dump_rows(path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: tuple(connection.execute(f"SELECT * FROM {table} ORDER BY 1"))
            for table in tables
        }


def test_sqlite_rows_equal_across_two_rebuilds(tmp_path):
    events = committed_events(tmp_path / "ledger")
    first = rebuild_sqlite(events, tmp_path / "a.sqlite3")
    second = rebuild_sqlite(events, tmp_path / "b.sqlite3")

    assert dump_rows(first) == dump_rows(second)
    assert first.read_bytes() == second.read_bytes()
    assert dump_rows(first)["applications"][0][:2] == (
        "application:test:1",
        "accepted",
    )


def test_sqlite_projection_has_only_required_projection_tables(tmp_path):
    path = rebuild_sqlite(committed_events(tmp_path / "ledger"), tmp_path / "ral.sqlite3")

    assert set(dump_rows(path)) == {
        "addresses",
        "applications",
        "attestations",
        "bindings",
        "claims",
        "deliveries",
        "projection_meta",
        "residents",
    }
