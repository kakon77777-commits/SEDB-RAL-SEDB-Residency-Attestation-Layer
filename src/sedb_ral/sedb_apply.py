from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from typing import Protocol

from .errors import RALValidationError


_FIELD_NAMESPACE = "sedb_ral"
_FIELD_VALUE_TYPE = "json"
_FIELD_SPECS = (
    ("ral.resident_id", "resident_id", "SEDB-RAL Resident ID", "SEDB-RAL projection for ral.resident_id."),
    ("ral.application_id", "application_id", "SEDB-RAL Application ID", "SEDB-RAL projection for ral.application_id."),
    ("ral.application_status", "application_status", "SEDB-RAL Application Status", "SEDB-RAL projection for ral.application_status."),
    ("ral.instance_refs", "instance_refs", "SEDB-RAL Instance References", "SEDB-RAL projection for ral.instance_refs."),
    ("ral.addresses", "addresses", "SEDB-RAL Addresses", "SEDB-RAL projection for ral.addresses."),
    ("ral.claims", "claims", "SEDB-RAL Claims", "SEDB-RAL projection for ral.claims."),
    ("ral.attestations", "attestations", "SEDB-RAL Attestations", "SEDB-RAL projection for ral.attestations."),
    ("ral.ledger_head", "ledger_head", "SEDB-RAL Ledger Head", "SEDB-RAL projection for ral.ledger_head."),
)
_RECORD_KEYS = frozenset({"id", "kind", "label", "values"})
_VALUE_PATHS = frozenset(path for path, _, _, _ in _FIELD_SPECS)
_FIELD_PAGE_SIZE = 100


class FieldServiceLike(Protocol):
    def get_field(self, field_id_or_key: str) -> dict[str, object]:
        raise NotImplementedError

    def list_fields(
        self,
        *,
        search: str = "",
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        raise NotImplementedError

    def create_field(
        self,
        *,
        key: str,
        label: str,
        value_type: str = "text",
        description: str = "",
        status: str = "active",
        namespace: str = "global",
    ) -> dict[str, object]:
        raise NotImplementedError


class EntityServiceLike(Protocol):
    def create_entity(
        self, *, label: str, kind: str = "record", entity_id: str | None = None
    ) -> dict[str, object]:
        raise NotImplementedError

    def get_entity(
        self, entity_id: str, *, include_cells: bool = True
    ) -> dict[str, object]:
        raise NotImplementedError

    def set_cell(
        self,
        entity_id: str,
        field_key: str,
        value: object,
        *,
        source: str = "",
        confidence: float | None = None,
    ) -> dict[str, object]:
        raise NotImplementedError


@dataclass(frozen=True)
class SEDBApplyResult:
    field_count: int
    entity_count: int
    cell_count: int
    reused_field_count: int
    reused_entity_count: int


class SEDBApplyError(RuntimeError):
    """An application failure with the operations known to have completed."""

    def __init__(
        self,
        *,
        progress: SEDBApplyResult,
        failed_operation: str,
        cause: Exception,
    ) -> None:
        self.progress = progress
        self.failed_operation = failed_operation
        self.cause = cause
        super().__init__(f"sedb_apply_failed: {failed_operation}: {cause}")


def _require_string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RALValidationError("sedb_apply_record_invalid", key)
    return value


def _require_json_value(value: object, path: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise RALValidationError("sedb_apply_value_invalid", path) from error


def _validated_records(
    records: Iterable[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    validated: list[Mapping[str, object]] = []
    record_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != _RECORD_KEYS:
            raise RALValidationError("sedb_apply_record_invalid", "exchange record")
        record_id = _require_string(record, "id")
        if record_id in record_ids:
            raise RALValidationError("sedb_apply_record_duplicate", record_id)
        if _require_string(record, "kind") != "ai_resident":
            raise RALValidationError("sedb_apply_record_invalid", "kind")
        _require_string(record, "label")
        values = record.get("values")
        if not isinstance(values, Mapping):
            raise RALValidationError("sedb_apply_record_invalid", "values")
        unknown_paths = set(values).difference(_VALUE_PATHS)
        if unknown_paths:
            raise RALValidationError(
                "sedb_apply_value_unmapped", min(str(path) for path in unknown_paths)
            )
        for path, value in values.items():
            _require_json_value(value, str(path))
        record_ids.add(record_id)
        validated.append(record)
    return tuple(sorted(validated, key=lambda record: str(record["id"])))


def _listed_fields(fields: FieldServiceLike) -> tuple[Mapping[str, object], ...]:
    listed: list[Mapping[str, object]] = []
    offset = 0
    while True:
        page = fields.list_fields(
            search="", status="", limit=_FIELD_PAGE_SIZE, offset=offset
        )
        if not isinstance(page, list) or not all(isinstance(field, Mapping) for field in page):
            raise RALValidationError("sedb_apply_field_list_invalid", "list_fields")
        listed.extend(page)
        if len(page) < _FIELD_PAGE_SIZE:
            return tuple(listed)
        offset += len(page)


def _field_ref_from_existing(
    listed_fields: Iterable[Mapping[str, object]], key: str
) -> str | None:
    candidates = [field for field in listed_fields if field.get("key") == key]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise RALValidationError("sedb_apply_field_conflict", key)
    field = candidates[0]
    if (
        field.get("namespace") != _FIELD_NAMESPACE
        or field.get("value_type") != _FIELD_VALUE_TYPE
    ):
        raise RALValidationError("sedb_apply_field_conflict", key)
    field_id = field.get("id")
    if not isinstance(field_id, str) or not field_id:
        raise RALValidationError("sedb_apply_field_invalid", key)
    return field_id


def _field_ref_from_created(field: object, key: str) -> str:
    if not isinstance(field, Mapping) or (
        field.get("namespace") != _FIELD_NAMESPACE
        or field.get("key") != key
        or field.get("value_type") != _FIELD_VALUE_TYPE
    ):
        raise RALValidationError("sedb_apply_field_conflict", key)
    field_id = field.get("id")
    if not isinstance(field_id, str) or not field_id:
        raise RALValidationError("sedb_apply_field_invalid", key)
    return field_id


def _require_compatible_entity(entity: object, record: Mapping[str, object]) -> None:
    if not isinstance(entity, Mapping) or (
        entity.get("label") != record["label"] or entity.get("kind") != record["kind"]
    ):
        raise RALValidationError("sedb_apply_entity_conflict", str(record["id"]))


def _progress(
    field_count: int,
    entity_count: int,
    cell_count: int,
    reused_field_count: int,
    reused_entity_count: int,
) -> SEDBApplyResult:
    return SEDBApplyResult(
        field_count=field_count,
        entity_count=entity_count,
        cell_count=cell_count,
        reused_field_count=reused_field_count,
        reused_entity_count=reused_entity_count,
    )


def apply_sedb_records(
    records: Iterable[Mapping[str, object]],
    fields: FieldServiceLike,
    entities: EntityServiceLike,
) -> SEDBApplyResult:
    """Apply exact exchange records through injected, SEDB-compatible services."""
    ordered_records = _validated_records(records)
    field_refs: dict[str, str] = {}
    missing_specs: list[tuple[str, str, str, str]] = []
    field_count = 0
    entity_count = 0
    cell_count = 0
    reused_field_count = 0
    reused_entity_count = 0
    operation = "list_fields"
    try:
        listed_fields = _listed_fields(fields)
        operation = "resolve_fields"
        for spec in _FIELD_SPECS:
            _, key, _, _ = spec
            field_ref = _field_ref_from_existing(listed_fields, key)
            if field_ref is None:
                missing_specs.append(spec)
            else:
                field_refs[key] = field_ref
        field_count = len(field_refs)
        reused_field_count = len(field_refs)

        for _, key, label, description in missing_specs:
            operation = f"create_field:{_FIELD_NAMESPACE}.{key}"
            created = fields.create_field(
                key=key,
                label=label,
                value_type=_FIELD_VALUE_TYPE,
                description=description,
                status="active",
                namespace=_FIELD_NAMESPACE,
            )
            field_refs[key] = _field_ref_from_created(created, key)
            field_count += 1

        for record in ordered_records:
            entity_id = str(record["id"])
            operation = f"get_entity:{entity_id}"
            try:
                existing = entities.get_entity(entity_id, include_cells=True)
            except KeyError:
                operation = f"create_entity:{entity_id}"
                entities.create_entity(
                    label=str(record["label"]),
                    kind=str(record["kind"]),
                    entity_id=entity_id,
                )
            else:
                operation = f"validate_entity:{entity_id}"
                _require_compatible_entity(existing, record)
                reused_entity_count += 1
            entity_count += 1

            values = record["values"]
            assert isinstance(values, Mapping)
            for ral_path, key, _, _ in _FIELD_SPECS:
                if ral_path not in values:
                    continue
                field_ref = field_refs[key]
                operation = f"set_cell:{entity_id}:{field_ref}"
                entities.set_cell(entity_id, field_ref, values[ral_path])
                cell_count += 1
    except SEDBApplyError:
        raise
    except Exception as cause:
        raise SEDBApplyError(
            progress=_progress(
                field_count,
                entity_count,
                cell_count,
                reused_field_count,
                reused_entity_count,
            ),
            failed_operation=operation,
            cause=cause,
        ) from cause

    return _progress(
        field_count,
        entity_count,
        cell_count,
        reused_field_count,
        reused_entity_count,
    )
