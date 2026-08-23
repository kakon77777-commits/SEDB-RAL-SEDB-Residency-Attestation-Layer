from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


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


def _difference(
    path: str,
    classification: str,
    expected: object,
    actual: object,
    rule_id: str | None = None,
) -> SEDBDifference:
    return SEDBDifference(path, classification, expected, actual, rule_id)


def _rules_by_path(
    mapping: Mapping[str, object],
) -> tuple[dict[str, Mapping[str, object]], tuple[SEDBDifference, ...]]:
    rules = mapping.get("rules")
    if not isinstance(rules, list):
        return {}, (
            _difference(
                "mapping.rules",
                "contradiction",
                "a list of exact profile rules",
                rules,
            ),
        )

    declared: dict[str, Mapping[str, object]] = {}
    for index, rule in enumerate(rules):
        path = f"mapping.rules[{index}]"
        if not isinstance(rule, Mapping):
            return {}, (
                _difference(path, "contradiction", "a mapping rule", rule),
            )
        rule_id = rule.get("rule_id")
        ral_path = rule.get("ral_path")
        classification = rule.get("classification")
        if not isinstance(rule_id, str) or not isinstance(ral_path, str):
            return {}, (
                _difference(
                    path,
                    "contradiction",
                    "a rule_id and ral_path",
                    rule,
                    rule_id if isinstance(rule_id, str) else None,
                ),
            )
        if classification not in {"mapped", "intentionally_unmapped"}:
            return {}, (
                _difference(
                    f"{path}.classification",
                    "contradiction",
                    "mapped or intentionally_unmapped",
                    classification,
                    rule_id,
                ),
            )
        if ral_path in declared:
            return {}, (
                _difference(
                    f"{path}.ral_path",
                    "contradiction",
                    "a unique declared RAL path",
                    ral_path,
                    rule_id,
                ),
            )
        declared[ral_path] = rule
    return declared, ()


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
    return rule.get("null_policy") == "drop_null" and expected is None and actual is MISSING


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
        elif actual_value is MISSING or actual_value != expected_value:
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
                    "expected_by_mapping",
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
    rules, rule_differences = _rules_by_path(mapping)
    if rule_differences:
        return SEDBDiffReport(rule_differences)

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

    canonical_expected_ids = tuple(sorted(expected_ids))
    if expected_ids != canonical_expected_ids:
        return SEDBDiffReport(
            (
                _difference(
                    "expected.records.order",
                    "contradiction",
                    canonical_expected_ids,
                    expected_ids,
                ),
            )
        )
    if set(expected_ids) == set(actual_ids) and actual_ids != canonical_expected_ids:
        return SEDBDiffReport(
            (
                _difference(
                    "records.order",
                    "contradiction",
                    canonical_expected_ids,
                    actual_ids,
                ),
            )
        )
    if expected_ids != actual_ids:
        expected_id = expected_ids[0] if expected_ids else MISSING
        actual_id = actual_ids[0] if actual_ids else MISSING
        return SEDBDiffReport(
            (
                _difference(
                    f"records[{expected_id}].id",
                    "contradiction",
                    expected_id,
                    actual_id,
                ),
            )
        )

    differences: list[SEDBDifference] = []
    for expected_record, actual_record, record_id in zip(
        expected_records, actual_records, expected_ids, strict=True
    ):
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
