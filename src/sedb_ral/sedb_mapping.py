from __future__ import annotations

from collections.abc import Mapping

from .errors import RALValidationError
from .projection import RegistryProjection


_FIELD_NAMESPACE = "sedb_ral"
_MISSING = object()
_DECLARED_PATHS = frozenset(
    {
        "ral.resident_id",
        "ral.application_id",
        "ral.application_status",
        "ral.instance_refs",
        "ral.addresses",
        "ral.claims",
        "ral.attestations",
        "ral.ledger_head",
    }
)
_UNMAPPED_PATHS = frozenset({"ral.authority"})


def _mapping_rules(mapping: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    if mapping.get("field_namespace") != _FIELD_NAMESPACE:
        raise RALValidationError(
            "sedb_mapping_namespace_invalid", "field namespace must be sedb_ral"
        )
    rules = mapping.get("rules")
    if not isinstance(rules, list):
        raise RALValidationError("sedb_mapping_profile_invalid", "rules must be a list")

    declared: dict[str, Mapping[str, object]] = {}
    intentionally_unmapped: set[str] = set()
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise RALValidationError(
                "sedb_mapping_profile_invalid", "each rule must be an object"
            )
        ral_path = rule.get("ral_path")
        classification = rule.get("classification")
        if not isinstance(ral_path, str):
            raise RALValidationError(
                "sedb_mapping_rule_unknown", "rule must declare a known RAL path"
            )
        if classification == "intentionally_unmapped":
            if ral_path not in _UNMAPPED_PATHS or rule.get("sedb_target") is not None:
                raise RALValidationError(
                    "sedb_mapping_rule_unknown", ral_path
                )
            if ral_path in intentionally_unmapped:
                raise RALValidationError("sedb_mapping_rule_duplicate", ral_path)
            intentionally_unmapped.add(ral_path)
            continue
        if classification != "mapped" or ral_path not in _DECLARED_PATHS:
            raise RALValidationError("sedb_mapping_rule_unknown", ral_path)
        if ral_path in declared:
            raise RALValidationError("sedb_mapping_rule_duplicate", ral_path)
        target = rule.get("sedb_target")
        expected_target = f"{_FIELD_NAMESPACE}.{ral_path.removeprefix('ral.')}"
        if target != expected_target or rule.get("value_transform") != "identity":
            raise RALValidationError("sedb_mapping_rule_invalid", ral_path)
        if rule.get("null_policy") != "preserve_null":
            raise RALValidationError("sedb_mapping_null_policy_invalid", ral_path)
        declared[ral_path] = rule

    missing = _DECLARED_PATHS.difference(declared)
    if missing:
        raise RALValidationError("sedb_mapping_rule_missing", min(missing))
    missing_unmapped = _UNMAPPED_PATHS.difference(intentionally_unmapped)
    if missing_unmapped:
        raise RALValidationError(
            "sedb_mapping_rule_missing", min(missing_unmapped)
        )
    return declared


def _value_for(
    projection: RegistryProjection,
    resident_id: str,
    resident: Mapping[str, object],
    ral_path: str,
) -> object:
    if ral_path == "ral.resident_id":
        return resident.get("resident_id", _MISSING)
    if ral_path == "ral.application_id":
        return resident.get("application_ref", _MISSING)
    if ral_path == "ral.application_status":
        application_id = resident.get("application_ref")
        application = projection.applications.get(application_id)
        if not isinstance(application, Mapping):
            return _MISSING
        return application.get("status", _MISSING)
    if ral_path == "ral.instance_refs":
        directory = projection.directory.get(resident_id)
        return directory.get("instance_refs", _MISSING) if directory else _MISSING
    if ral_path == "ral.addresses":
        directory = projection.directory.get(resident_id)
        return directory.get("addresses", _MISSING) if directory else _MISSING
    if ral_path == "ral.claims":
        return resident.get("claims", _MISSING)
    if ral_path == "ral.attestations":
        return resident.get("attestations", _MISSING)
    if ral_path == "ral.ledger_head":
        return projection.source_event_ids[-1] if projection.source_event_ids else _MISSING
    raise AssertionError(f"unreachable declared path: {ral_path}")


def project_to_sedb_records(
    projection: RegistryProjection, mapping: Mapping[str, object]
) -> tuple[dict[str, object], ...]:
    """Project a registry snapshot into deterministic, side-effect-free SEDB records."""
    rules = _mapping_rules(mapping)
    records: list[dict[str, object]] = []
    for resident in projection.residents.values():
        resident_id = resident.get("resident_id")
        label = resident.get("display_label")
        if not isinstance(resident_id, str) or not resident_id:
            raise RALValidationError("sedb_mapping_resident_id_invalid", "resident_id")
        if not isinstance(label, str) or not label:
            raise RALValidationError("sedb_mapping_label_invalid", resident_id)

        values: dict[str, object] = {}
        for ral_path in sorted(rules):
            value = _value_for(projection, resident_id, resident, ral_path)
            if value is _MISSING or (ral_path == "ral.addresses" and value == []):
                continue
            values[ral_path] = value
        records.append(
            {
                "id": resident_id,
                "kind": "ai_resident",
                "label": label,
                "values": values,
            }
        )
    return tuple(sorted(records, key=lambda record: str(record["id"])))
