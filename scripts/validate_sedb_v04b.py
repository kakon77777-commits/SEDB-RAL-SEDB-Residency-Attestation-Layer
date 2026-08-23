from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from typing import Any

from sedb_ral.projection import RegistryProjection
from sedb_ral.sedb_adoption import extract_verified_sedb
from sedb_ral.sedb_apply import SEDBApplyResult, apply_sedb_records
from sedb_ral.sedb_mapping import project_to_sedb_records


@dataclass(frozen=True)
class SEDBIntegrationResult:
    temp_root: Path
    package_root: Path
    database_path: Path
    export_path: Path
    database_integrity: str
    apply_result: SEDBApplyResult
    expected_record_count: int
    exported_record_count: int
    raw_exported_records: tuple[dict[str, object], ...]
    exported_records: tuple[dict[str, object], ...]
    records_match: bool
    export_shape_adapter: str
    execution_claim: str


def _sedb_module_names() -> tuple[str, ...]:
    return tuple(
        name for name in sys.modules if name == "sedb" or name.startswith("sedb.")
    )


def _assert_module_from(module: ModuleType, source_root: Path) -> None:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        raise RuntimeError(f"sedb_import_origin_unavailable:{module.__name__}")
    if not Path(module_file).resolve(strict=True).is_relative_to(source_root):
        raise RuntimeError(f"sedb_import_origin_mismatch:{module.__name__}")


@contextmanager
def _isolated_sedb_api(
    source_root: Path,
) -> Iterator[tuple[type[Any], type[Any], type[Any], type[Any]]]:
    source_root = source_root.resolve(strict=True)
    original_path = list(sys.path)
    saved_modules = {name: sys.modules[name] for name in _sedb_module_names()}
    for name in saved_modules:
        del sys.modules[name]
    sys.path.insert(0, str(source_root))
    try:
        from sedb.db import Database
        from sedb.entities import EntityService
        from sedb.exchange import ExchangeService
        from sedb.fields import FieldService

        for service in (Database, FieldService, EntityService, ExchangeService):
            _assert_module_from(sys.modules[service.__module__], source_root)
        yield Database, FieldService, EntityService, ExchangeService
    finally:
        sys.path[:] = original_path
        for name in _sedb_module_names():
            del sys.modules[name]
        sys.modules.update(saved_modules)


def _package_root(extracted_root: Path, profile: Mapping[str, object]) -> Path:
    archive_filename = profile.get("archive_filename")
    if not isinstance(archive_filename, str) or not archive_filename.endswith(".zip"):
        raise ValueError("sedb_archive_incompatible:archive_filename_mismatch")
    package_root = extracted_root / archive_filename.removesuffix(".zip")
    if not package_root.is_dir() or not (package_root / "src" / "sedb").is_dir():
        raise ValueError("sedb_archive_incompatible:package_root_missing")
    return package_root


def _read_export(path: Path) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"sedb_export_record_invalid:{line_number}")
            records.append(record)
    return tuple(records)


def _adapt_sedb_export(
    records: tuple[dict[str, object], ...], mapping: Mapping[str, object]
) -> tuple[dict[str, object], ...]:
    namespace = mapping.get("field_namespace")
    rules = mapping.get("rules")
    if not isinstance(namespace, str) or not isinstance(rules, list):
        raise ValueError("sedb_export_mapping_invalid")

    ral_paths_by_local_key: dict[str, str] = {}
    mapped_ral_paths: set[str] = set()
    for rule in rules:
        if not isinstance(rule, Mapping) or rule.get("classification") != "mapped":
            continue
        ral_path = rule.get("ral_path")
        sedb_target = rule.get("sedb_target")
        if not isinstance(ral_path, str) or not isinstance(sedb_target, str):
            raise ValueError("sedb_export_mapping_invalid")
        target_namespace, separator, local_key = sedb_target.partition(".")
        if target_namespace != namespace or separator != "." or not local_key:
            raise ValueError(f"sedb_export_mapping_invalid:{ral_path}")
        if local_key in ral_paths_by_local_key:
            raise ValueError(f"sedb_export_mapping_duplicate:{local_key}")
        if ral_path in mapped_ral_paths:
            raise ValueError(
                f"sedb_export_mapping_duplicate_destination:{ral_path}"
            )
        ral_paths_by_local_key[local_key] = ral_path
        mapped_ral_paths.add(ral_path)

    adapted: list[dict[str, object]] = []
    for line_number, record in enumerate(records, start=1):
        if set(record) != {"id", "kind", "label", "values"}:
            raise ValueError(f"sedb_export_record_invalid:{line_number}")
        values = record["values"]
        if not isinstance(values, Mapping):
            raise ValueError(f"sedb_export_record_invalid:{line_number}")
        adapted_values: dict[str, object] = {}
        for local_key, value in values.items():
            ral_path = ral_paths_by_local_key.get(str(local_key))
            if ral_path is None:
                ral_path = f"sedb_unmapped.{local_key}"
            adapted_values[ral_path] = value
        adapted.append(
            {
                "id": record["id"],
                "kind": record["kind"],
                "label": record["label"],
                "values": adapted_values,
            }
        )
    return tuple(adapted)


def _tracked_database_type(database_type: type[Any]) -> type[Any]:
    connections: list[Any] = []

    class TrackedDatabase(database_type):
        def connect(self) -> Any:
            connection = super().connect()
            connections.append(connection)
            return connection

        @classmethod
        def close_connection(cls, connection: Any) -> None:
            try:
                connection.close()
            finally:
                connections[:] = [
                    tracked for tracked in connections if tracked is not connection
                ]

        @classmethod
        def close_all_connections(cls) -> None:
            first_error: Exception | None = None
            while connections:
                connection = connections.pop()
                try:
                    connection.close()
                except Exception as error:
                    if first_error is None:
                        first_error = error
            if first_error is not None:
                raise first_error

    return TrackedDatabase


def run_integration(
    archive: str | Path,
    adoption_profile: Mapping[str, object],
    projection: RegistryProjection,
    mapping: Mapping[str, object],
    output: str | Path,
) -> SEDBIntegrationResult:
    expected_records = project_to_sedb_records(projection, mapping)
    expected_record_count = len(expected_records)

    output_root = Path(output).resolve(strict=True)
    if not output_root.is_dir():
        raise NotADirectoryError(output_root)
    temp_root = Path(
        tempfile.mkdtemp(prefix="sedb-ral-v04b-", dir=output_root)
    ).resolve(strict=True)
    extracted_root = extract_verified_sedb(
        archive,
        adoption_profile,
        temp_root / "extracted",
    )
    package_root = _package_root(extracted_root, adoption_profile)
    database_path = temp_root / "sedb.sqlite"
    export_path = temp_root / "sedb-export.jsonl"

    with _isolated_sedb_api(package_root / "src") as api:
        Database, FieldService, EntityService, ExchangeService = api
        TrackedDatabase = _tracked_database_type(Database)
        database = None
        fields = None
        entities = None
        exchange = None
        try:
            database = TrackedDatabase(database_path)
            fields = FieldService(database)
            entities = EntityService(database)
            exchange = ExchangeService(database)

            apply_result = apply_sedb_records(expected_records, fields, entities)
            pragma_connection = database.connect()
            try:
                integrity_rows = tuple(
                    str(row[0])
                    for row in pragma_connection.execute("PRAGMA integrity_check")
                )
            finally:
                TrackedDatabase.close_connection(pragma_connection)
            database_integrity = (
                "ok" if integrity_rows == ("ok",) else "\n".join(integrity_rows)
            )
            exported_record_count = exchange.export_jsonl(export_path)
        finally:
            exchange = None
            entities = None
            fields = None
            database = None
            TrackedDatabase.close_all_connections()

    raw_exported_records = _read_export(export_path)
    exported_records = _adapt_sedb_export(raw_exported_records, mapping)
    records_match = (
        exported_record_count == len(raw_exported_records)
        and exported_records == expected_records
    )
    return SEDBIntegrationResult(
        temp_root=temp_root,
        package_root=package_root,
        database_path=database_path,
        export_path=export_path,
        database_integrity=database_integrity,
        apply_result=apply_result,
        expected_record_count=expected_record_count,
        exported_record_count=exported_record_count,
        raw_exported_records=raw_exported_records,
        exported_records=exported_records,
        records_match=records_match,
        export_shape_adapter="v04b_local_field_keys_to_ral_paths",
        execution_claim="own_execution",
    )
