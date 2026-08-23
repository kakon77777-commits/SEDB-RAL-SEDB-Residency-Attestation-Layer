from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .errors import RALValidationError


_FIELD_NAMESPACE = "sedb_ral"
_FIELD_TYPE = "json"
_FIELD_SPECS = (
    ("ral.resident_id", "resident_id"),
    ("ral.application_id", "application_id"),
    ("ral.application_status", "application_status"),
    ("ral.instance_refs", "instance_refs"),
    ("ral.addresses", "addresses"),
    ("ral.claims", "claims"),
    ("ral.attestations", "attestations"),
    ("ral.ledger_head", "ledger_head"),
)
_RECORD_KEYS = frozenset({"id", "kind", "label", "values"})
_VALUE_PATHS = frozenset(path for path, _ in _FIELD_SPECS)


class FieldServiceLike(Protocol):
    """Minimal field-service boundary; an absent field raises ``KeyError``."""

    def get_field(self, field_id_or_key: str) -> dict[str, object]:
        raise NotImplementedError

    def create_field(self, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError


class EntityServiceLike(Protocol):
    """Minimal entity and sparse-cell service boundary."""

    def create_entity(self, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError

    def create_cell(self, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError


@dataclass(frozen=True)
class SEDBApplyResult:
    field_count: int
    entity_count: int
    cell_count: int
    reused_field_count: int


def _field_id(key: str) -> str:
    return f"{_FIELD_NAMESPACE}.{key}"


def _require_string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise RALValidationError("sedb_apply_record_invalid", key)
    return value


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
        record_ids.add(record_id)
        validated.append(record)
    return tuple(sorted(validated, key=lambda record: str(record["id"])))


def _require_compatible_field(field: object, key: str) -> None:
    if not isinstance(field, Mapping) or (
        field.get("namespace") != _FIELD_NAMESPACE
        or field.get("key") != key
        or field.get("field_type") != _FIELD_TYPE
    ):
        raise RALValidationError("sedb_apply_field_conflict", _field_id(key))


def apply_sedb_records(
    records: Iterable[Mapping[str, object]],
    fields: FieldServiceLike,
    entities: EntityServiceLike,
) -> SEDBApplyResult:
    """Apply exact SEDB-RAL exchange records through injected service protocols."""
    ordered_records = _validated_records(records)

    missing_keys: list[str] = []
    reused_field_count = 0
    for _, key in _FIELD_SPECS:
        try:
            field = fields.get_field(_field_id(key))
        except KeyError:
            missing_keys.append(key)
        else:
            _require_compatible_field(field, key)
            reused_field_count += 1

    for key in missing_keys:
        field = fields.create_field(
            namespace=_FIELD_NAMESPACE,
            key=key,
            field_type=_FIELD_TYPE,
        )
        _require_compatible_field(field, key)

    cell_count = 0
    for record in ordered_records:
        entity_id = str(record["id"])
        entities.create_entity(
            entity_id=entity_id,
            kind=str(record["kind"]),
            label=str(record["label"]),
        )
        values = record["values"]
        assert isinstance(values, Mapping)
        for ral_path, key in _FIELD_SPECS:
            if ral_path not in values:
                continue
            entities.create_cell(
                entity_id=entity_id,
                field_id_or_key=_field_id(key),
                value=values[ral_path],
            )
            cell_count += 1

    return SEDBApplyResult(
        field_count=len(_FIELD_SPECS),
        entity_count=len(ordered_records),
        cell_count=cell_count,
        reused_field_count=reused_field_count,
    )
