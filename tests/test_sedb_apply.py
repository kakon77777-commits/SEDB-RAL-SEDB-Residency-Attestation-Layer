from __future__ import annotations

from collections.abc import Iterable, Mapping

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.sedb_apply import SEDBApplyError, apply_sedb_records


FIELD_SPECS = (
    ("resident_id", "SEDB-RAL Resident ID", "SEDB-RAL projection for ral.resident_id."),
    ("application_id", "SEDB-RAL Application ID", "SEDB-RAL projection for ral.application_id."),
    ("application_status", "SEDB-RAL Application Status", "SEDB-RAL projection for ral.application_status."),
    ("instance_refs", "SEDB-RAL Instance References", "SEDB-RAL projection for ral.instance_refs."),
    ("addresses", "SEDB-RAL Addresses", "SEDB-RAL projection for ral.addresses."),
    ("claims", "SEDB-RAL Claims", "SEDB-RAL projection for ral.claims."),
    ("attestations", "SEDB-RAL Attestations", "SEDB-RAL projection for ral.attestations."),
    ("ledger_head", "SEDB-RAL Ledger Head", "SEDB-RAL projection for ral.ledger_head."),
)
FIELD_IDS = {key: f"field:{key}" for key, _, _ in FIELD_SPECS}


def field_record(
    key: str, *, value_type: str = "json", namespace: str = "sedb_ral"
) -> dict[str, object]:
    label, description = next(
        (label, description)
        for item_key, label, description in FIELD_SPECS
        if item_key == key
    )
    return {
        "id": FIELD_IDS[key],
        "key": key,
        "label": label,
        "description": description,
        "value_type": value_type,
        "namespace": namespace,
        "status": "active",
    }


class FakeFields:
    def __init__(
        self,
        events: list[str],
        existing: Iterable[Mapping[str, object]] = (),
        fail_create_key: str | None = None,
        fail_list: bool = False,
    ):
        self.events = events
        self.fields = {str(field["id"]): dict(field) for field in existing}
        self.fail_create_key = fail_create_key
        self.fail_list = fail_list

    def get_field(self, field_id_or_key: str) -> dict[str, object]:
        self.events.append(f"get_field:{field_id_or_key}")
        try:
            return self.fields[field_id_or_key]
        except KeyError:
            raise KeyError(field_id_or_key) from None

    def list_fields(
        self,
        *,
        search: str = "",
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        self.events.append(f"list_fields:{search}:{status}:{limit}:{offset}")
        if self.fail_list:
            raise RuntimeError("field discovery failed")
        candidates = sorted(self.fields.values(), key=lambda field: str(field["id"]))
        if search:
            candidates = [
                field
                for field in candidates
                if search in str(field["key"]) or search in str(field["label"])
            ]
        if status:
            candidates = [field for field in candidates if field["status"] == status]
        return candidates[offset : offset + limit]

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
        self.events.append(f"create_field:{namespace}:{key}:{value_type}")
        if key == self.fail_create_key:
            raise RuntimeError(f"field write failed for {key}")
        field = {
            "id": FIELD_IDS[key],
            "key": key,
            "label": label,
            "value_type": value_type,
            "description": description,
            "status": status,
            "namespace": namespace,
        }
        self.fields[str(field["id"])] = field
        return field


class FakeEntities:
    def __init__(
        self,
        events: list[str],
        existing: Iterable[Mapping[str, object]] = (),
        fail_create: bool = False,
        fail_set_field_id: str | None = None,
    ):
        self.events = events
        self.entities = {str(entity["id"]): dict(entity) for entity in existing}
        self.cells: dict[tuple[str, str], object] = {}
        self.fail_create = fail_create
        self.fail_set_field_id = fail_set_field_id

    def create_entity(
        self, *, label: str, kind: str = "record", entity_id: str | None = None
    ) -> dict[str, object]:
        self.events.append(f"create_entity:{entity_id}:{kind}")
        if self.fail_create:
            raise RuntimeError("entity write failed")
        if entity_id is None:
            raise ValueError("fake requires caller-supplied entity ID")
        if entity_id in self.entities:
            raise ValueError(f"duplicate entity {entity_id}")
        entity = {"id": entity_id, "label": label, "kind": kind}
        self.entities[entity_id] = entity
        return entity

    def get_entity(self, entity_id: str, *, include_cells: bool = True) -> dict[str, object]:
        self.events.append(f"get_entity:{entity_id}:{include_cells}")
        try:
            return self.entities[entity_id]
        except KeyError:
            raise KeyError(entity_id) from None

    def set_cell(
        self,
        entity_id: str,
        field_key: str,
        value: object,
        *,
        source: str = "",
        confidence: float | None = None,
    ) -> dict[str, object]:
        self.events.append(f"set_cell:{entity_id}:{field_key}")
        if field_key == self.fail_set_field_id:
            self.fail_set_field_id = None
            raise RuntimeError(f"cell write failed for {field_key}")
        self.cells[(entity_id, field_key)] = value
        return {
            "entity_id": entity_id,
            "field_key": field_key,
            "value": value,
            "source": source,
            "confidence": confidence,
        }


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


def test_apply_uses_real_service_shapes_and_returned_field_ids():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events)

    result = apply_sedb_records(RECORDS, fields, entities)

    assert result.field_count == 8
    assert result.entity_count == 1
    assert result.cell_count == 8
    assert result.reused_field_count == 0
    assert result.reused_entity_count == 0
    assert events == [
        "list_fields:::100:0",
        *(f"create_field:sedb_ral:{key}:json" for key, _, _ in FIELD_SPECS),
        "get_entity:resident:test:True",
        "create_entity:resident:test:ai_resident",
        *(f"set_cell:resident:test:field:{key}" for key, _, _ in FIELD_SPECS),
    ]
    assert list(fields.fields.values()) == [field_record(key) for key, _, _ in FIELD_SPECS]
    assert entities.cells[("resident:test", "field:application_status")] is None


def test_apply_reuses_partial_existing_fields_and_entity_on_retry():
    events: list[str] = []
    fields = FakeFields(events, [field_record("resident_id")])
    entities = FakeEntities(
        events,
        [{"id": "resident:test", "label": "Test Resident", "kind": "ai_resident"}],
    )

    result = apply_sedb_records(RECORDS, fields, entities)

    assert result.field_count == 8
    assert result.reused_field_count == 1
    assert result.entity_count == 1
    assert result.reused_entity_count == 1
    assert "create_field:sedb_ral:resident_id:json" not in events
    assert "create_entity:resident:test:ai_resident" not in events
    assert len(entities.cells) == 8


@pytest.mark.parametrize(
    "existing",
    [
        [field_record("resident_id", namespace="other")],
        [field_record("resident_id", value_type="text")],
    ],
)
def test_apply_rejects_conflicting_field_before_any_write(existing):
    events: list[str] = []
    fields = FakeFields(events, existing)
    entities = FakeEntities(events)

    with pytest.raises(SEDBApplyError) as exc:
        apply_sedb_records(RECORDS, fields, entities)

    assert exc.value.failed_operation == "resolve_fields"
    assert isinstance(exc.value.cause, RALValidationError)
    assert exc.value.progress.field_count == 0
    assert events == ["list_fields:::100:0"]
    assert entities.entities == {}
    assert entities.cells == {}


def test_field_discovery_failure_reports_zero_progress():
    events: list[str] = []
    fields = FakeFields(events, fail_list=True)
    entities = FakeEntities(events)

    with pytest.raises(SEDBApplyError) as exc:
        apply_sedb_records(RECORDS, fields, entities)

    assert exc.value.failed_operation == "list_fields"
    assert isinstance(exc.value.cause, RuntimeError)
    assert exc.value.progress.field_count == 0
    assert exc.value.progress.entity_count == 0
    assert exc.value.progress.cell_count == 0
    assert events == ["list_fields:::100:0"]
    assert entities.entities == {}
    assert entities.cells == {}


def test_whitespace_label_is_rejected_before_any_service_call():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events)
    records = ({**RECORDS[0], "label": " \t "},)

    with pytest.raises(RALValidationError, match="sedb_apply_record_invalid"):
        apply_sedb_records(records, fields, entities)

    assert events == []
    assert fields.fields == {}
    assert entities.entities == {}
    assert entities.cells == {}


@pytest.mark.parametrize("value", [object(), float("nan"), float("inf")])
def test_non_json_or_nonfinite_value_is_rejected_before_any_service_call(value):
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events)
    records = (
        {
            **RECORDS[0],
            "values": {"ral.resident_id": value},
        },
    )

    with pytest.raises(RALValidationError, match="sedb_apply_value_invalid"):
        apply_sedb_records(records, fields, entities)

    assert events == []
    assert fields.fields == {}
    assert entities.entities == {}
    assert entities.cells == {}


def test_apply_rejects_unmapped_authority_before_any_service_call():
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
    assert entities.cells[("resident:null", "field:resident_id")] is None
    assert ("resident:null", "field:addresses") not in entities.cells
    assert False not in entities.cells.values()


def test_field_write_failure_reports_completed_progress_and_persisted_state():
    events: list[str] = []
    fields = FakeFields(events, fail_create_key="application_id")
    entities = FakeEntities(events)

    with pytest.raises(SEDBApplyError) as exc:
        apply_sedb_records(RECORDS, fields, entities)

    assert exc.value.failed_operation == "create_field:sedb_ral.application_id"
    assert isinstance(exc.value.cause, RuntimeError)
    assert exc.value.progress.field_count == 1
    assert exc.value.progress.entity_count == 0
    assert exc.value.progress.cell_count == 0
    assert list(fields.fields) == ["field:resident_id"]
    assert entities.entities == {}


def test_entity_write_failure_reports_completed_fields_and_no_entity():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events, fail_create=True)

    with pytest.raises(SEDBApplyError) as exc:
        apply_sedb_records(RECORDS, fields, entities)

    assert exc.value.failed_operation == "create_entity:resident:test"
    assert isinstance(exc.value.cause, RuntimeError)
    assert exc.value.progress.field_count == 8
    assert exc.value.progress.entity_count == 0
    assert exc.value.progress.cell_count == 0
    assert len(fields.fields) == 8
    assert entities.entities == {}


def test_mid_cell_failure_reports_progress_and_retry_upserts_cells():
    events: list[str] = []
    fields = FakeFields(events)
    entities = FakeEntities(events, fail_set_field_id="field:application_status")

    with pytest.raises(SEDBApplyError) as exc:
        apply_sedb_records(RECORDS, fields, entities)

    assert exc.value.failed_operation == "set_cell:resident:test:field:application_status"
    assert isinstance(exc.value.cause, RuntimeError)
    assert exc.value.progress.field_count == 8
    assert exc.value.progress.entity_count == 1
    assert exc.value.progress.cell_count == 2
    assert len(fields.fields) == 8
    assert entities.entities == {
        "resident:test": {
            "id": "resident:test",
            "label": "Test Resident",
            "kind": "ai_resident",
        }
    }
    assert len(entities.cells) == 2

    retry = apply_sedb_records(RECORDS, fields, entities)

    assert retry.reused_field_count == 8
    assert retry.reused_entity_count == 1
    assert retry.cell_count == 8
    assert len(fields.fields) == 8
    assert len(entities.entities) == 1
    assert len(entities.cells) == 8


def test_existing_entity_label_or_kind_conflict_reports_resolved_fields():
    events: list[str] = []
    fields = FakeFields(events, [field_record(key) for key, _, _ in FIELD_SPECS])
    entities = FakeEntities(
        events,
        [{"id": "resident:test", "label": "Wrong Label", "kind": "ai_resident"}],
    )

    with pytest.raises(SEDBApplyError) as exc:
        apply_sedb_records(RECORDS, fields, entities)

    assert exc.value.failed_operation == "validate_entity:resident:test"
    assert isinstance(exc.value.cause, RALValidationError)
    assert exc.value.progress.field_count == 8
    assert exc.value.progress.reused_field_count == 8
    assert exc.value.progress.entity_count == 0
    assert entities.cells == {}
