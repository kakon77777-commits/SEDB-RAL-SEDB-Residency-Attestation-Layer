from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .canonical import canonical_bytes
from .sedb_mapping import validate_sedb_mapping


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()
_CLASSIFICATIONS = (
    "expected_by_mapping",
    "unmapped",
    "contradiction",
)
_RECORD_KEYS = frozenset({"id", "kind", "label", "values"})


@dataclass(frozen=True)
class SEDBDifference:
    path: str
    classification: str
    expected: object
    actual: object
    rule_id: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "classification": self.classification,
            "expected": _presence_envelope(self.expected),
            "actual": _presence_envelope(self.actual),
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True)
class SEDBDiffReport:
    differences: tuple[SEDBDifference, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            classification: sum(
                difference.classification == classification
                for difference in self.differences
            )
            for classification in _CLASSIFICATIONS
        }

    @property
    def passed(self) -> bool:
        return self.counts["contradiction"] == 0

    def as_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "counts": self.counts,
            "differences": [difference.as_json() for difference in self.differences],
        }


def _difference(
    path: str,
    classification: str,
    expected: object,
    actual: object,
    rule_id: str | None = None,
) -> SEDBDifference:
    return SEDBDifference(path, classification, expected, actual, rule_id)


def _presence_envelope(value: object) -> dict[str, object]:
    if value is MISSING:
        return {"presence": "missing"}
    return {"presence": "present", "value": _diagnostic_value(value)}


def _diagnostic_value(value: object) -> object:
    if isinstance(value, (set, frozenset)):
        items = [_diagnostic_value(item) for item in value]
        items.sort(key=canonical_bytes)
        return {
            "diagnostic_collection": type(value).__name__,
            "items": items,
        }
    if isinstance(value, tuple):
        return {
            "diagnostic_collection": "tuple",
            "items": [_diagnostic_value(item) for item in value],
        }
    if isinstance(value, list):
        return [_diagnostic_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _diagnostic_value(item) for key, item in value.items()}
    return value


def _all_rules(mapping: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    mapped_rules = validate_sedb_mapping(mapping)
    all_rules = dict(mapped_rules)
    rules = mapping["rules"]
    assert isinstance(rules, list)
    for rule in rules:
        assert isinstance(rule, Mapping)
        if rule["classification"] == "intentionally_unmapped":
            ral_path = rule["ral_path"]
            assert isinstance(ral_path, str)
            all_rules[ral_path] = rule
    return all_rules


def _record_ids(
    records: tuple[Mapping[str, object], ...], side: str
) -> tuple[tuple[str, ...], tuple[SEDBDifference, ...]]:
    ids: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        path = f"{side}[{index}]"
        if set(record) != _RECORD_KEYS:
            return (), (
                _difference(path, "contradiction", _RECORD_KEYS, set(record)),
            )
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            return (), (
                _difference(f"{path}.id", "contradiction", "a non-empty id", record_id),
            )
        if record_id in seen:
            return (), (
                _difference(
                    f"records[{record_id}].id",
                    "contradiction",
                    "a unique record id",
                    record_id,
                ),
            )
        seen.add(record_id)
        ids.append(record_id)
    return tuple(ids), ()


def _expected_by_mapping(
    rule: Mapping[str, object], expected: object, actual: object
) -> bool:
    if rule.get("classification") == "intentionally_unmapped" and actual is MISSING:
        return True
    return False


def _json_exact_equal(expected: object, actual: object) -> bool:
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, Mapping):
        assert isinstance(actual, Mapping)
        return set(expected) == set(actual) and all(
            _json_exact_equal(expected[key], actual[key]) for key in expected
        )
    if isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple))
        return len(expected) == len(actual) and all(
            _json_exact_equal(expected_value, actual_value)
            for expected_value, actual_value in zip(expected, actual, strict=True)
        )
    return expected == actual


def _compare_values(
    record_id: str,
    expected: Mapping[str, object],
    actual: Mapping[str, object],
    rules: Mapping[str, Mapping[str, object]],
) -> list[SEDBDifference]:
    differences: list[SEDBDifference] = []
    for ral_path in sorted(expected):
        expected_value = expected[ral_path]
        actual_value = actual.get(ral_path, MISSING)
        path = f"records[{record_id}].values.{ral_path}"
        rule = rules.get(ral_path)
        if rule is None:
            differences.append(
                _difference(path, "contradiction", "a declared mapped path", expected_value)
            )
        elif actual_value is MISSING and _expected_by_mapping(
            rule, expected_value, actual_value
        ):
            differences.append(
                _difference(
                    path,
                    "expected_by_mapping",
                    expected_value,
                    actual_value,
                    str(rule["rule_id"]),
                )
            )
        elif actual_value is MISSING or not _json_exact_equal(
            expected_value, actual_value
        ):
            differences.append(
                _difference(
                    path,
                    "contradiction",
                    expected_value,
                    actual_value,
                    str(rule["rule_id"]),
                )
            )

    for ral_path in sorted(set(actual).difference(expected)):
        actual_value = actual[ral_path]
        path = f"records[{record_id}].values.{ral_path}"
        rule = rules.get(ral_path)
        if rule is None:
            differences.append(
                _difference(path, "unmapped", MISSING, actual_value)
            )
        elif rule.get("classification") == "intentionally_unmapped":
            differences.append(
                _difference(
                    path,
                    "unmapped",
                    MISSING,
                    actual_value,
                    str(rule["rule_id"]),
                )
            )
        else:
            differences.append(
                _difference(
                    path,
                    "contradiction",
                    MISSING,
                    actual_value,
                    str(rule["rule_id"]),
                )
            )
    return differences


def compare_sedb_projection(
    expected: Iterable[Mapping[str, object]],
    actual: Iterable[Mapping[str, object]],
    mapping: Mapping[str, object],
) -> SEDBDiffReport:
    """Classify exact SEDB projection differences using only mapping rules."""
    rules = _all_rules(mapping)

    expected_records = tuple(expected)
    actual_records = tuple(actual)
    if not all(isinstance(record, Mapping) for record in expected_records + actual_records):
        return SEDBDiffReport(
            (
                _difference(
                    "records", "contradiction", "exchange record mappings", "non-mapping record"
                ),
            )
        )
    expected_ids, expected_id_differences = _record_ids(expected_records, "expected")
    if expected_id_differences:
        return SEDBDiffReport(expected_id_differences)
    actual_ids, actual_id_differences = _record_ids(actual_records, "actual")
    if actual_id_differences:
        return SEDBDiffReport(actual_id_differences)

    differences: list[SEDBDifference] = []
    expected_by_id = dict(zip(expected_ids, expected_records, strict=True))
    actual_by_id = dict(zip(actual_ids, actual_records, strict=True))
    expected_id_set = set(expected_ids)
    actual_id_set = set(actual_ids)
    for record_id in sorted(expected_id_set.difference(actual_id_set)):
        differences.append(
            _difference(
                f"records[{record_id}]",
                "contradiction",
                expected_by_id[record_id],
                MISSING,
            )
        )
    for record_id in sorted(actual_id_set.difference(expected_id_set)):
        differences.append(
            _difference(
                f"records[{record_id}]",
                "contradiction",
                MISSING,
                actual_by_id[record_id],
            )
        )
    if expected_id_set == actual_id_set and expected_ids != actual_ids:
        differences.append(
            _difference(
                "records.order",
                "contradiction",
                expected_ids,
                actual_ids,
            )
        )

    for record_id in sorted(expected_id_set.intersection(actual_id_set)):
        expected_record = expected_by_id[record_id]
        actual_record = actual_by_id[record_id]
        for key in ("kind", "label"):
            if expected_record[key] != actual_record[key]:
                differences.append(
                    _difference(
                        f"records[{record_id}].{key}",
                        "contradiction",
                        expected_record[key],
                        actual_record[key],
                    )
                )
        expected_values = expected_record["values"]
        actual_values = actual_record["values"]
        if not isinstance(expected_values, Mapping) or not isinstance(actual_values, Mapping):
            differences.append(
                _difference(
                    f"records[{record_id}].values",
                    "contradiction",
                    "a values mapping",
                    actual_values,
                )
            )
            continue
        differences.extend(
            _compare_values(record_id, expected_values, actual_values, rules)
        )

    return SEDBDiffReport(tuple(differences))
