from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path

from .canonical import canonical_bytes
from .projection import project_events

_TABLES = (
    "applications",
    "residents",
    "addresses",
    "bindings",
    "claims",
    "attestations",
    "deliveries",
    "projection_meta",
)


def _json(value: object) -> str:
    if isinstance(value, tuple):
        value = list(value)
    return canonical_bytes(value).decode("utf-8")


def _events(value: Iterable[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    return tuple(dict(item) for item in sorted(value, key=lambda item: item["ledger_seq"]))


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE applications (application_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE residents (resident_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE addresses (address_id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE bindings (binding_id TEXT PRIMARY KEY, subject_ref TEXT NOT NULL, object_kind TEXT NOT NULL, object_ref TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE claims (claim_id TEXT PRIMARY KEY, claimant_ref TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE attestations (attestation_id TEXT PRIMARY KEY, claim_ref TEXT NOT NULL, verification_status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, stage TEXT, payload TEXT NOT NULL);
        CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )


def rebuild_sqlite(
    events: Iterable[Mapping[str, object]], path: Path
) -> Path:
    """Rebuild a disposable SQLite query projection from canonical ledger events."""
    values = _events(events)
    projection = project_events(values)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    attestations: dict[str, Mapping[str, object]] = {}
    deliveries: dict[str, Mapping[str, object]] = {}
    bindings: dict[str, Mapping[str, object]] = {}
    claims = dict(projection.claims)
    for event in values:
        event_type = event["event_type"]
        payload = event["payload"]
        if event_type == "claim.recorded":
            claim = payload["claim"]
            claims[claim["claim_id"]] = claim
        elif event_type == "attestation.recorded":
            attestation = payload["attestation"]
            attestations[attestation["attestation_id"]] = attestation
        elif event_type == "binding.recorded":
            binding = payload["binding"]
            bindings[binding["binding_id"]] = binding
        elif event_type.startswith("delivery."):
            delivery = payload.get("delivery", payload)
            if isinstance(delivery, Mapping) and "delivery_id" in delivery:
                deliveries[str(delivery["delivery_id"])] = delivery

    for resident_id, resident in projection.residents.items():
        for instance in resident["instances"]:
            binding_id = f"binding:instance:{instance['instance_id']}"
            bindings[binding_id] = {
                "binding_id": binding_id,
                "subject_ref": resident_id,
                "object_kind": "instance",
                "object_ref": instance["instance_id"],
                "valid_from_event": "projection:resident.registered",
                "valid_until_event": None,
            }
        for address in resident["addresses"]:
            binding_id = f"binding:address:{address['address_id']}"
            bindings[binding_id] = {
                "binding_id": binding_id,
                "subject_ref": resident_id,
                "object_kind": "address",
                "object_ref": address["address_id"],
                "valid_from_event": "projection:resident.registered",
                "valid_until_event": None,
            }

    connection = sqlite3.connect(path)
    try:
        with connection:
            _create_schema(connection)
            connection.executemany(
                "INSERT INTO applications VALUES (?, ?, ?)",
                [
                    (key, value["status"], _json(value))
                    for key, value in sorted(projection.applications.items())
                ],
            )
            connection.executemany(
                "INSERT INTO residents VALUES (?, ?, ?)",
                [
                    (key, value["status"], _json(value))
                    for key, value in sorted(projection.residents.items())
                ],
            )
            connection.executemany(
                "INSERT INTO addresses VALUES (?, ?, ?, ?)",
                [
                    (address["address_id"], resident_id, address["status"], _json(address))
                    for resident_id, resident in sorted(projection.residents.items())
                    for address in sorted(resident["addresses"], key=lambda item: item["address_id"])
                ],
            )
            connection.executemany(
                "INSERT INTO bindings VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        key,
                        value["subject_ref"],
                        value["object_kind"],
                        value["object_ref"],
                        _json(value),
                    )
                    for key, value in sorted(bindings.items())
                ],
            )
            connection.executemany(
                "INSERT INTO claims VALUES (?, ?, ?)",
                [
                    (key, value["claimant_ref"], _json(value))
                    for key, value in sorted(claims.items())
                ],
            )
            connection.executemany(
                "INSERT INTO attestations VALUES (?, ?, ?, ?)",
                [
                    (key, value["claim_ref"], value["verification_status"], _json(value))
                    for key, value in sorted(attestations.items())
                ],
            )
            connection.executemany(
                "INSERT INTO deliveries VALUES (?, ?, ?)",
                [
                    (key, value.get("stage"), _json(value))
                    for key, value in sorted(deliveries.items())
                ],
            )
            connection.executemany(
                "INSERT INTO projection_meta VALUES (?, ?)",
                [
                    ("applied_corrections", _json(projection.applied_corrections)),
                    ("source_event_count", str(len(values))),
                    ("source_event_ids", _json(projection.source_event_ids)),
                    ("unapplied_event_ids", _json(projection.unapplied_event_ids)),
                ],
            )
    finally:
        connection.close()
    return path


def table_row_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in _TABLES
        }
    finally:
        connection.close()
