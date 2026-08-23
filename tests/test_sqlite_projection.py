import copy
import json
import sqlite3
from pathlib import Path

from sedb_ral.application import commit_application, evaluate_application
from sedb_ral.ledger import read_verified_events
from sedb_ral.sqlite_projection import rebuild_sqlite
from sedb_ral.contracts import validate_contract

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
    application = copy.deepcopy(APPLICATION["application"])
    application["addresses"] = [
        {
            "schema_version": "0.1",
            "address_id": "address:test:1",
            "namespace": "codex_thread",
            "adapter_kind": "codex_queue",
            "locator": "019fe51e-9276-7f63-8c16-414624b7fa9d",
            "target_ref": "resident:test",
            "status": "active",
        }
    ]
    decision = evaluate_application(
        application,
        APPLICATION["authorities"],
        verified_attestation_refs=frozenset({"attestation:neo:1"}),
    )
    receipt = commit_application(
        tmp_path,
        application,
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


def test_every_derived_binding_uses_exact_registered_event_provenance(tmp_path):
    events = committed_events(tmp_path / "ledger")
    path = rebuild_sqlite(events, tmp_path / "ral.sqlite3")
    event_ids = {item["event_id"] for item in events}
    registered_id = next(
        item["event_id"]
        for item in events
        if item["event_type"] == "resident.registered"
    )

    with sqlite3.connect(path) as connection:
        payloads = [
            json.loads(row[0])
            for row in connection.execute("SELECT payload FROM bindings ORDER BY 1")
        ]

    assert {item["object_kind"] for item in payloads} == {"instance", "address"}
    for binding in payloads:
        validate_contract("binding.schema.json", binding)
        assert binding["schema_version"] == "0.1"
        assert binding["valid_from_event"] == registered_id
        assert binding["valid_from_event"] in event_ids
