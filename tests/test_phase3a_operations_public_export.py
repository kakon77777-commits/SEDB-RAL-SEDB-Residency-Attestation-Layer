from __future__ import annotations

import hashlib
import json

import pytest
from test_limen_public_view_cli import committed_ledger

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.operations.public_export import (
    export_public,
    seam_source_manifest,
)

EXPECTED_SCHEMA_ID = "https://evemisslab.com/schemas/limen/ral-view-v0.2.json"
EXPECTED_SOURCE_COMMIT = "077606f08576b38e93762d7eb4d8720b36766fc1"
EXPECTED_SHA256 = "32aefbb92345538b0320930e237f35791c0c43c5a1f7e40eace5d7248d803373"


def test_seam_manifest_pins_exact_ral_source_without_foreign_schema_body():
    value = seam_source_manifest()

    assert value["schema_id"] == EXPECTED_SCHEMA_ID
    assert value["schema_version"] == "0.2"
    assert value["source_commit"] == EXPECTED_SOURCE_COMMIT
    assert value["raw_bytes"] == 6029
    assert value["raw_sha256"] == EXPECTED_SHA256
    assert value["foreign_schema_pins"] == []
    assert "schema_body" not in value


def test_public_export_matches_existing_core_and_is_create_new(tmp_path):
    ledger, head, _ = committed_ledger(tmp_path)
    output = tmp_path / "public" / "ral-view.json"
    output.parent.mkdir()

    receipt = export_public(
        ledger_root=ledger,
        expected_head=head,
        sequence=4,
        destination=output,
    )

    value = json.loads(output.read_text(encoding="utf-8"))
    assert hashlib.sha256(output.read_bytes()).hexdigest() == receipt["raw_sha256"]
    assert receipt["view_digest"] == sha256_ref(value)
    assert receipt["ledger_head"] == head
    assert receipt["registry_writes"] == 0
    assert receipt["fabric_events"] == 0
    original = output.read_bytes()
    with pytest.raises(RALValidationError) as caught:
        export_public(
            ledger_root=ledger,
            expected_head=head,
            sequence=4,
            destination=output,
        )
    assert caught.value.code == "operations_public_output_exists"
    assert output.read_bytes() == original


def test_public_export_contains_no_operations_or_transport_material(tmp_path):
    ledger, head, _ = committed_ledger(tmp_path)
    output = tmp_path / "view.json"

    export_public(
        ledger_root=ledger,
        expected_head=head,
        sequence=4,
        destination=output,
    )

    serialized = canonical_bytes(json.loads(output.read_text(encoding="utf-8"))).lower()
    for marker in (
        b"operator_observation",
        b"authority_artifact",
        b"policy_digest",
        b"ai_home",
        b"fabric_payload_class",
        b"realm",
        b"delivery_state",
        b"adoption",
    ):
        assert marker not in serialized
