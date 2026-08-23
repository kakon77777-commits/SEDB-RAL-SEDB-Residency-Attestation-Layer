import copy
import json
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.sedb_diff import MISSING, compare_sedb_projection
from sedb_ral.sedb_mapping import validate_sedb_mapping


ROOT = Path(__file__).parents[1]
MAPPING = json.loads(
    (ROOT / "profiles" / "sedb-v0.4b-mapping.json").read_text(encoding="utf-8")
)
EXPECTED = (
    {
        "id": "resident:a",
        "kind": "ai_resident",
        "label": "Alpha",
        "values": {
            "ral.resident_id": "resident:a",
            "ral.application_status": None,
        },
    },
)


def test_comparator_reuses_the_task3_mapping_validator():
    rules = validate_sedb_mapping(MAPPING)

    assert set(rules) == {
        "ral.resident_id",
        "ral.application_id",
        "ral.application_status",
        "ral.instance_refs",
        "ral.addresses",
        "ral.claims",
        "ral.attestations",
        "ral.ledger_head",
    }


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda mapping: mapping.__setitem__("field_namespace", "wrong"), "sedb_mapping_namespace_invalid"),
        (lambda mapping: mapping["rules"][0].__setitem__("sedb_target", "wrong.target"), "sedb_mapping_rule_invalid"),
        (lambda mapping: mapping["rules"][0].__setitem__("value_transform", "coerce"), "sedb_mapping_rule_invalid"),
        (lambda mapping: mapping["rules"][0].__setitem__("null_policy", "drop_null"), "sedb_mapping_null_policy_invalid"),
        (lambda mapping: mapping["rules"][0].__setitem__("ral_path", "ral.unknown"), "sedb_mapping_rule_unknown"),
        (lambda mapping: mapping["rules"].append(copy.deepcopy(mapping["rules"][0])), "sedb_mapping_rule_duplicate"),
        (lambda mapping: mapping.__setitem__("rules", mapping["rules"][1:]), "sedb_mapping_rule_missing"),
        (lambda mapping: mapping.__setitem__("rules", mapping["rules"][:-1]), "sedb_mapping_rule_missing"),
    ],
)
def test_invalid_mapping_is_rejected_before_comparison(mutation, error_code):
    mapping = copy.deepcopy(MAPPING)
    mutation(mapping)

    with pytest.raises(RALValidationError, match=error_code):
        compare_sedb_projection(EXPECTED, EXPECTED, mapping)


def test_declared_intentionally_unmapped_value_is_expected_difference():
    expected = (
        {
            **EXPECTED[0],
            "values": {**EXPECTED[0]["values"], "ral.authority": {"scope": "local"}},
        },
    )

    report = compare_sedb_projection(expected=expected, actual=EXPECTED, mapping=MAPPING)

    assert report.counts == {
        "expected_by_mapping": 1,
        "unmapped": 0,
        "contradiction": 0,
    }
    assert report.differences[0].rule_id == "authority"


def test_actual_intentionally_unmapped_value_is_visible_but_not_expected():
    actual = (
        {
            **EXPECTED[0],
            "values": {**EXPECTED[0]["values"], "ral.authority": {"scope": "local"}},
        },
    )

    report = compare_sedb_projection(EXPECTED, actual, MAPPING)

    assert report.passed is True
    assert report.counts == {
        "expected_by_mapping": 0,
        "unmapped": 1,
        "contradiction": 0,
    }
    assert report.differences[0].rule_id == "authority"


def test_unmapped_actual_extra_does_not_fail_but_is_visible():
    actual = (
        {
            **EXPECTED[0],
            "values": {**EXPECTED[0]["values"], "ral.future": "visible"},
        },
    )

    report = compare_sedb_projection(EXPECTED, actual, MAPPING)

    assert report.passed is True
    assert report.counts == {
        "expected_by_mapping": 0,
        "unmapped": 1,
        "contradiction": 0,
    }
    assert report.differences[0].path == "records[resident:a].values.ral.future"
    assert report.differences[0].expected is MISSING
    assert report.differences[0].actual == "visible"
    assert report.differences[0].rule_id is None


def test_mapped_value_change_is_the_sole_contradiction():
    actual = (
        {
            **EXPECTED[0],
            "values": {
                **EXPECTED[0]["values"],
                "ral.resident_id": "resident:wrong",
            },
        },
    )

    report = compare_sedb_projection(EXPECTED, actual, MAPPING)

    assert report.passed is False
    assert report.counts == {
        "expected_by_mapping": 0,
        "unmapped": 0,
        "contradiction": 1,
    }
    assert report.differences[0].rule_id == "resident-id"


def test_false_is_not_equivalent_to_a_mapped_null():
    actual = (
        {
            **EXPECTED[0],
            "values": {
                **EXPECTED[0]["values"],
                "ral.application_status": False,
            },
        },
    )

    report = compare_sedb_projection(EXPECTED, actual, MAPPING)

    assert report.passed is False
    assert report.counts["contradiction"] == 1
    assert report.differences[0].expected is None
    assert report.differences[0].actual is False


@pytest.mark.parametrize(
    ("ral_path", "expected_value", "actual_value"),
    [
        ("ral.application_status", False, 0),
        ("ral.application_status", True, 1),
        ("ral.application_status", 0, 0.0),
        (
            "ral.instance_refs",
            [False, {"nested": True}],
            [0, {"nested": 1}],
        ),
    ],
)
def test_json_value_equality_requires_exact_types(
    ral_path, expected_value, actual_value
):
    expected = (
        {
            **EXPECTED[0],
            "values": {
                **EXPECTED[0]["values"],
                ral_path: expected_value,
            },
        },
    )
    actual = (
        {
            **expected[0],
            "values": {
                **expected[0]["values"],
                ral_path: actual_value,
            },
        },
    )

    report = compare_sedb_projection(expected, actual, MAPPING)

    assert report.passed is False
    assert report.counts["contradiction"] == 1


def test_missing_mapped_value_is_a_contradiction():
    actual = ({**EXPECTED[0], "values": {"ral.resident_id": "resident:a"}},)

    report = compare_sedb_projection(EXPECTED, actual, MAPPING)

    assert report.passed is False
    assert report.counts["contradiction"] == 1
    assert report.differences[0].actual is MISSING


def test_identity_kind_and_label_changes_each_fail():
    for key, value in (
        ("id", "resident:other"),
        ("kind", "other_kind"),
        ("label", "Other"),
    ):
        report = compare_sedb_projection(
            EXPECTED, ({**EXPECTED[0], key: value},), MAPPING
        )

        assert report.passed is False
        assert report.counts["contradiction"] >= 1


def test_canonical_id_order_is_a_profile_semantic_not_iteration_accident():
    expected = (
        EXPECTED[0],
        {
            **EXPECTED[0],
            "id": "resident:b",
            "label": "Beta",
            "values": {
                "ral.resident_id": "resident:b",
                "ral.application_status": None,
            },
        },
    )

    report = compare_sedb_projection(expected, tuple(reversed(expected)), MAPPING)

    assert report.passed is False
    assert report.counts == {
        "expected_by_mapping": 0,
        "unmapped": 0,
        "contradiction": 1,
    }
    assert report.differences[0].path == "records.order"


def test_expected_only_and_actual_only_ids_have_exact_missing_differences():
    actual = ({**EXPECTED[0], "id": "resident:unknown"},)

    report = compare_sedb_projection(EXPECTED, actual, MAPPING)

    assert report.passed is False
    assert report.counts == {
        "expected_by_mapping": 0,
        "unmapped": 0,
        "contradiction": 2,
    }
    assert report.differences == (
        report.differences[0].__class__(
            path="records[resident:a]",
            classification="contradiction",
            expected=EXPECTED[0],
            actual=MISSING,
            rule_id=None,
        ),
        report.differences[1].__class__(
            path="records[resident:unknown]",
            classification="contradiction",
            expected=MISSING,
            actual=actual[0],
            rule_id=None,
        ),
    )


def test_duplicate_id_fails_closed():
    duplicate = compare_sedb_projection(EXPECTED, (EXPECTED[0], EXPECTED[0]), MAPPING)

    assert duplicate.passed is False
    assert any(difference.path.endswith(".id") for difference in duplicate.differences)


def test_json_report_preserves_missing_and_null_for_canonical_serialization():
    missing_mapped = compare_sedb_projection(
        EXPECTED,
        ({**EXPECTED[0], "values": {"ral.resident_id": "resident:a"}},),
        MAPPING,
    )
    missing_and_extra_record = compare_sedb_projection(
        EXPECTED, ({**EXPECTED[0], "id": "resident:unknown"},), MAPPING
    )
    null_difference = compare_sedb_projection(
        EXPECTED,
        (
            {
                **EXPECTED[0],
                "values": {
                    **EXPECTED[0]["values"],
                    "ral.application_status": False,
                },
            },
        ),
        MAPPING,
    )

    payload = {
        "missing_mapped": missing_mapped.as_json(),
        "missing_and_extra_record": missing_and_extra_record.as_json(),
        "null_difference": null_difference.as_json(),
    }

    assert payload["missing_mapped"]["differences"][0]["actual"] == {
        "presence": "missing"
    }
    assert payload["missing_and_extra_record"]["differences"][0]["actual"] == {
        "presence": "missing"
    }
    assert payload["missing_and_extra_record"]["differences"][1]["expected"] == {
        "presence": "missing"
    }
    assert payload["null_difference"]["differences"][0]["expected"] == {
        "presence": "present",
        "value": None,
    }
    assert json.loads(json.dumps(payload)) == payload
    assert canonical_bytes(payload)


def test_malformed_record_collections_have_stable_canonical_diagnostics():
    malformed = (
        {
            "id": "resident:a",
            "kind": "ai_resident",
            "label": "Alpha",
        },
    )

    report = compare_sedb_projection(EXPECTED, malformed, MAPPING)
    payload = report.as_json()

    assert report.passed is False
    assert payload["differences"][0]["expected"]["value"] == {
        "diagnostic_collection": "frozenset",
        "items": ["id", "kind", "label", "values"],
    }
    assert payload["differences"][0]["actual"]["value"] == {
        "diagnostic_collection": "set",
        "items": ["id", "kind", "label"],
    }
    assert canonical_bytes(payload) == canonical_bytes(report.as_json())
