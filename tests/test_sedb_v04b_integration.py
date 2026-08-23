import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from scripts.validate_sedb_v04b import _adapt_sedb_export, run_integration
from sedb_ral.errors import RALValidationError
from sedb_ral.projection import RegistryProjection
from sedb_ral.sedb_mapping import project_to_sedb_records


ROOT = Path(__file__).parents[1]
ARCHIVE = Path(r"C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip")
ADOPTION_PROFILE = json.loads(
    (ROOT / "profiles" / "sedb-v0.4b-adoption.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "profiles" / "sedb-v0.4b-mapping.json").read_text(encoding="utf-8")
)
CLAIM = {
    "schema_version": "0.1",
    "claim_id": "claim:test:1",
    "claimant_ref": "resident:test",
    "subject_ref": "resident:test",
    "predicate": "display_label",
    "object": "Test Resident",
    "claimed_time": None,
    "claimed_authored_by_instance": "instance:test:1",
    "claimed_on_behalf_of_line": None,
}
INSTANCE = {
    "schema_version": "0.1",
    "instance_id": "instance:test:1",
    "resident_ref": "resident:test",
    "runtime_tag": "runtime:claude-code",
    "started_time_ref": "ctcl:instant:test",
    "ended_time_ref": None,
}
PROJECTION = RegistryProjection(
    applications={"application:test:1": {"status": "accepted"}},
    residents={
        "resident:test": {
            "resident_id": "resident:test",
            "application_ref": "application:test:1",
            "display_label": "Test Resident",
            "instances": [INSTANCE],
            "addresses": [],
            "claims": [CLAIM],
        }
    },
    directory={
        "resident:test": {
            "instance_refs": ["instance:test:1"],
            "addresses": [],
        }
    },
    claims={"claim:test:1": CLAIM},
    resident_source_event_ids={"resident:test": "evt:resident:1"},
    applied_corrections=(),
    unapplied_event_ids=(),
    unapplied_reasons={},
    source_event_ids=("evt:authority:1", "evt:resident:1"),
)


def _require_exact_archive() -> None:
    if not ARCHIVE.exists():
        pytest.skip("archive_unavailable")


def test_real_sedb_v04b_round_trip_uses_only_temp_storage(tmp_path):
    _require_exact_archive()
    expected_records = project_to_sedb_records(PROJECTION, MAPPING)
    loaded_before = {name for name in sys.modules if name == "sedb" or name.startswith("sedb.")}

    result = run_integration(
        ARCHIVE,
        ADOPTION_PROFILE,
        PROJECTION,
        MAPPING,
        tmp_path,
    )

    assert result.database_integrity == "ok"
    assert result.apply_result.field_count == 8
    assert result.apply_result.entity_count == len(expected_records)
    assert result.apply_result.cell_count == sum(
        len(record["values"]) for record in expected_records
    )
    assert result.expected_record_count == len(expected_records)
    assert result.exported_record_count == len(expected_records)
    assert result.exported_records == expected_records
    assert result.records_match is True
    assert result.export_shape_adapter == "v04b_local_field_keys_to_ral_paths"
    assert set(result.raw_exported_records[0]["values"]) == {
        "application_id",
        "application_status",
        "attestations",
        "claims",
        "instance_refs",
        "ledger_head",
        "resident_id",
    }
    assert result.execution_claim == "own_execution"
    assert result.temp_root.parent == tmp_path.resolve()
    assert result.database_path == result.temp_root / "sedb.sqlite"
    assert result.export_path == result.temp_root / "sedb-export.jsonl"
    assert result.package_root == result.temp_root / "extracted" / "SEDB-v0.4B-local"
    assert result.database_path.is_file()
    assert result.export_path.is_file()
    assert result.package_root.is_dir()
    assert {
        name for name in sys.modules if name == "sedb" or name.startswith("sedb.")
    } == loaded_before


def test_real_integration_temp_tree_deletes_immediately_without_gc():
    _require_exact_archive()

    with tempfile.TemporaryDirectory(prefix="sedb-ral-v04b-cleanup-") as output:
        result = run_integration(
            ARCHIVE,
            ADOPTION_PROFILE,
            PROJECTION,
            MAPPING,
            output,
        )
        temp_root = result.temp_root
        database_path = result.database_path
        raw_exported_records = result.raw_exported_records

        shutil.rmtree(temp_root)

        assert not temp_root.exists()
        assert result.database_path == database_path
        assert result.raw_exported_records == raw_exported_records


def test_invalid_mapping_fails_before_temp_tree_or_sedb_runtime(tmp_path):
    invalid_mapping = copy.deepcopy(MAPPING)
    invalid_mapping["rules"][0]["sedb_target"] = "sedb_ral.wrong"
    loaded_before = {name for name in sys.modules if name == "sedb" or name.startswith("sedb.")}

    with pytest.raises(RALValidationError, match="sedb_mapping_rule_invalid"):
        run_integration(
            ARCHIVE,
            ADOPTION_PROFILE,
            PROJECTION,
            invalid_mapping,
            tmp_path,
        )

    assert list(tmp_path.iterdir()) == []
    assert {
        name for name in sys.modules if name == "sedb" or name.startswith("sedb.")
    } == loaded_before


def test_present_wrong_archive_fails_instead_of_skipping(tmp_path):
    wrong_archive = tmp_path / ADOPTION_PROFILE["archive_filename"]
    wrong_archive.write_bytes(b"not the pinned SEDB archive")
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(ValueError, match="archive_size_mismatch"):
        run_integration(
            wrong_archive,
            ADOPTION_PROFILE,
            PROJECTION,
            MAPPING,
            output,
        )


def test_v04b_export_adapter_restores_ral_paths_from_checked_in_mapping():
    raw_records = (
        {
            "id": "resident:test",
            "kind": "ai_resident",
            "label": "Test Resident",
            "values": {
                "resident_id": "resident:test",
                "application_status": None,
            },
        },
    )

    assert _adapt_sedb_export(raw_records, MAPPING) == (
        {
            "id": "resident:test",
            "kind": "ai_resident",
            "label": "Test Resident",
            "values": {
                "ral.application_status": None,
                "ral.resident_id": "resident:test",
            },
        },
    )


def test_v04b_export_adapter_preserves_unknown_field_for_comparison():
    raw_records = (
        {
            "id": "resident:test",
            "kind": "ai_resident",
            "label": "Test Resident",
            "values": {"authority": {"scope": "forbidden"}},
        },
    )

    assert _adapt_sedb_export(raw_records, MAPPING) == (
        {
            "id": "resident:test",
            "kind": "ai_resident",
            "label": "Test Resident",
            "values": {
                "sedb_unmapped.authority": {"scope": "forbidden"},
            },
        },
    )


def test_v04b_export_adapter_rejects_duplicate_local_key_before_adaptation():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"][1]["sedb_target"] = mapping["rules"][0]["sedb_target"]

    with pytest.raises(
        ValueError,
        match="sedb_export_mapping_duplicate:resident_id",
    ):
        _adapt_sedb_export((), mapping)


def test_v04b_export_adapter_rejects_duplicate_ral_path_before_adaptation():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"][1]["ral_path"] = mapping["rules"][0]["ral_path"]

    with pytest.raises(
        ValueError,
        match="sedb_export_mapping_duplicate_destination:ral.resident_id",
    ):
        _adapt_sedb_export((), mapping)
