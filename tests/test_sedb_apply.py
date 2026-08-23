from __future__ import annotations

from collections.abc import Mapping

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.sedb_apply import apply_sedb_records


FIELD_KEYS = (
    "resident_id",
    "application_id",
    "application_status",
    "instance_refs",
    "addresses",
    "claims",
    "attestations",
    "ledger_head",
)


class FakeFields:
    def __init__(self, events: list[str], existing: Mapping[str, object] | None = None):
        self.events = events
        self.fields = dict(existing or {})

    def get_field(self, field_id_or_key: str) -> dict[str, object]:
        self.events.append(f"get_field:{field_id_or_key}")
        field = self.fields.get(field_id_or_key)
        if not isinstance(field, dict):
            raise KeyError(field_id_or_key)
        return field

    def create_field(self, **kwargs: object) -> dict[str, object]:
        namespace = kwargs["namespace"]
        key = kwargs["key"]
        assert isinstance(namespace, str)
        assert isinstance(key, str)
        field_id = f"{namespace}.{key}"
        self.events.append(f"create_field:{field_id}")
        field = dict(kwargs)
        self.fields[field_id] = field
        return field


class FakeEntities:
    def __init__(self, events: list[str]):
        self.events = events
        self.entities: dict[str, dict[str, object]] = {}
        self.cells: dict[tuple[str, str], object] = {}

    def create_entity(self, **kwargs: object) -> dict[str, object]:
        entity_id = kwargs["entity_id"]
        assert isinstance(entity_id, str)
        self.events.append(f"create_entity:{entity_id}")
        entity = dict(kwargs)
        self.entities[entity_id] = entity
        return entity

    def create_cell(self, **kwargs: object) -> dict[str, object]:
        entity_id = kwargs["entity_id"]
        field_id_or_key = kwargs["field_id_or_key"]
        assert isinstance(entity_id, str)
        assert isinstance(field_id_or_key, str)
        self.events.append(f"create_cell:{entity_id}:{field_id_or_key}")
        self.cells[(entity_id, field_id_or_key)] = kwargs["value"]
        return dict(kwargs)


RECORDS = (
    {
        "id": "resident:test",
        "kind": "ai_resident",
        "label": "Test Resident",
        "values": {
            "ral.resident_id": "resident:test",
            "ral.application_id": "application:test:1",
            "ral.application_status": None,
            "ral.instance_refs": ["instance:test:1"],
            "ral.addresses": [{"address_id": "address:test:1"}],
            "ral.claims": [{"claim_id": "claim:test:1"}],
            "ral.attestations": [],
            "ral.ledger_head": "evt:resident:1",
        },
    },
)


def test_apply_creates_declared_fields_then_entities_and_exact_cells():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events)

    result = apply_sedb_records(RECORDS, fields, entities)

    assert result.field_count == 8
    assert result.entity_count == 1
    assert result.cell_count == 8
    assert result.reused_field_count == 0
    assert events == [
        *(f"get_field:sedb_ral.{key}" for key in FIELD_KEYS),
        *(f"create_field:sedb_ral.{key}" for key in FIELD_KEYS),
        "create_entity:resident:test",
        *(f"create_cell:resident:test:sedb_ral.{key}" for key in FIELD_KEYS),
    ]
    assert fields.fields == {
        f"sedb_ral.{key}": {
            "namespace": "sedb_ral",
            "key": key,
            "field_type": "json",
        }
        for key in FIELD_KEYS
    }
    assert entities.entities == {
        "resident:test": {
            "entity_id": "resident:test",
            "kind": "ai_resident",
            "label": "Test Resident",
        }
    }
    assert entities.cells[("resident:test", "sedb_ral.application_status")] is None


def test_apply_reuses_compatible_declared_field():
    events: list[str] = []
    fields = FakeFields(
        events,
        {
            "sedb_ral.resident_id": {
                "namespace": "sedb_ral",
                "key": "resident_id",
                "field_type": "json",
            }
        },
    )
    entities = FakeEntities(events)

    result = apply_sedb_records(RECORDS, fields, entities)

    assert result.field_count == 8
    assert result.reused_field_count == 1
    assert "create_field:sedb_ral.resident_id" not in events


@pytest.mark.parametrize(
    "existing_field",
    [
        {"namespace": "other", "key": "resident_id", "field_type": "json"},
        {"namespace": "sedb_ral", "key": "resident_id", "field_type": "text"},
    ],
)
def test_apply_rejects_preexisting_namespace_or_type_conflict(existing_field):
    events: list[str] = []
    fields = FakeFields(events, {"sedb_ral.resident_id": existing_field})
    entities = FakeEntities(events)

    with pytest.raises(RALValidationError, match="sedb_apply_field_conflict"):
        apply_sedb_records(RECORDS, fields, entities)

    assert events == ["get_field:sedb_ral.resident_id"]
    assert entities.entities == {}
    assert entities.cells == {}


def test_apply_omits_absent_values_and_preserves_explicit_null():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events)
    records = (
        {
            "id": "resident:null",
            "kind": "ai_resident",
            "label": "Null Resident",
            "values": {"ral.resident_id": None},
        },
    )

    result = apply_sedb_records(records, fields, entities)

    assert result.cell_count == 1
    assert entities.cells[("resident:null", "sedb_ral.resident_id")] is None
    assert ("resident:null", "sedb_ral.addresses") not in entities.cells
    assert False not in entities.cells.values()


def test_apply_rejects_unmapped_authority_without_creating_services_state():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events)
    records = (
        {
            "id": "resident:authority",
            "kind": "ai_resident",
            "label": "Authority Resident",
            "values": {"ral.authority": {"scope": "forbidden"}},
        },
    )

    with pytest.raises(RALValidationError, match="sedb_apply_value_unmapped"):
        apply_sedb_records(records, fields, entities)

    assert events == []
    assert fields.fields == {}
    assert entities.entities == {}
    assert entities.cells == {}
