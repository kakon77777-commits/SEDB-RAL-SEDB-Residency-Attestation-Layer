from __future__ import annotations

import hashlib
from pathlib import Path

from ..canonical import canonical_bytes
from ..contracts import default_schema_root
from ..errors import RALValidationError
from ..ledger import read_verified_events
from ..limen_public_view import build_limen_public_view
from ..projection import project_events
from ..registry_root_contracts import bind_document_digest

RAL_VIEW_SCHEMA_ID = "https://evemisslab.com/schemas/limen/ral-view-v0.2.json"
RAL_VIEW_SOURCE_COMMIT = "077606f08576b38e93762d7eb4d8720b36766fc1"
RAL_VIEW_RAW_BYTES = 6029
RAL_VIEW_RAW_SHA256 = "32aefbb92345538b0320930e237f35791c0c43c5a1f7e40eace5d7248d803373"


def seam_source_manifest() -> dict[str, object]:
    path = default_schema_root() / "limen-ral-view-v0.2.schema.json"
    raw = path.read_bytes()
    observed_hash = hashlib.sha256(raw).hexdigest()
    if len(raw) != RAL_VIEW_RAW_BYTES or observed_hash != RAL_VIEW_RAW_SHA256:
        raise RALValidationError(
            "ral_seam_source_drift",
            "RAL public-view source differs from the approved J0 pin",
        )
    return bind_document_digest(
        {
            "schema": "sedb-ral.fabric-seam-source-manifest/0.1",
            "schema_id": RAL_VIEW_SCHEMA_ID,
            "schema_version": "0.2",
            "source_repository": (
                "https://github.com/kakon77777-commits/"
                "SEDB-RAL-SEDB-Residency-Attestation-Layer"
            ),
            "source_commit": RAL_VIEW_SOURCE_COMMIT,
            "raw_bytes": len(raw),
            "raw_sha256": observed_hash,
            "profile_ref": "sedb-ral.fabric-seam-source/v0.1",
            "foreign_schema_pins": [],
            "not_claimed": [
                "fabric_schema",
                "fabric_event",
                "delivery",
                "adoption",
                "production_activation",
            ],
        },
        "manifest_digest",
    )


def export_public(
    *,
    ledger_root: Path,
    expected_head: str,
    sequence: int,
    destination: Path,
) -> dict[str, object]:
    events = read_verified_events(Path(ledger_root), expected_head)
    if not events:
        raise RALValidationError(
            "external_anchor_mismatch", "public export requires a non-empty ledger"
        )
    view = build_limen_public_view(
        project_events(events),
        ledger_head=expected_head,
        sequence=sequence,
    )
    value = view.to_dict()
    raw = canonical_bytes(value)
    destination = Path(destination)
    if not destination.parent.is_dir():
        raise RALValidationError(
            "operations_public_output_parent_unavailable",
            "public output parent is unavailable",
        )
    try:
        with destination.open("xb") as stream:
            stream.write(raw)
    except FileExistsError as error:
        raise RALValidationError(
            "operations_public_output_exists", "public output already exists"
        ) from error
    return bind_document_digest(
        {
            "schema": "sedb-ral.operations-public-export-receipt/0.1",
            "source_schema_id": RAL_VIEW_SCHEMA_ID,
            "source_schema_sha256": RAL_VIEW_RAW_SHA256,
            "ledger_head": expected_head,
            "sequence": sequence,
            "view_digest": view.digest,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_bytes": len(raw),
            "registry_writes": 0,
            "private_reads": 0,
            "network_calls": 0,
            "external_sends": 0,
            "fabric_events": 0,
            "not_claimed": [
                "fabric_event",
                "delivery",
                "adoption",
                "production_activation",
            ],
        },
        "receipt_digest",
    )
