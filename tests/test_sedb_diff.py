import copy

from sedb_ral.sedb_diff import MISSING, compare_sedb_projection


MAPPING = {
    "field_namespace": "sedb_ral",
    "rules": [
        {
            "rule_id": "resident-id",
            "ral_path": "ral.resident_id",
            "sedb_target": "sedb_ral.resident_id",
            "value_transform": "identity",
            "null_policy": "preserve_null",
            "classification": "mapped",
        },
        {
            "rule_id": "status",
            "ral_path": "ral.application_status",
            "sedb_target": "sedb_ral.application_status",
            "value_transform": "identity",
            "null_policy": "preserve_null",
            "classification": "mapped",
        },
        {
            "rule_id": "authority",
            "ral_path": "ral.authority",
            "sedb_target": None,
            "value_transform": "not_applicable",
            "null_policy": "preserve_null",
            "classification": "intentionally_unmapped",
        },
    ],
}
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


def test_declared_null_drop_is_expected_difference():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"][1]["null_policy"] = "drop_null"

    report = compare_sedb_projection(
        EXPECTED,
        (
            {
                **EXPECTED[0],
                "values": {"ral.resident_id": "resident:a"},
            },
        ),
        mapping,
    )

    assert report.counts == {
        "expected_by_mapping": 1,
        "unmapped": 0,
        "contradiction": 0,
    }
    assert report.passed is True
    assert report.differences[0].path == (
        "records[resident:a].values.ral.application_status"
    )
    assert report.differences[0].rule_id == "status"


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


def test_unknown_id_and_duplicate_id_each_fail_closed():
    unknown = compare_sedb_projection(
        EXPECTED, ({**EXPECTED[0], "id": "resident:unknown"},), MAPPING
    )
    duplicate = compare_sedb_projection(EXPECTED, (EXPECTED[0], EXPECTED[0]), MAPPING)

    assert unknown.passed is False
    assert any(difference.path.endswith(".id") for difference in unknown.differences)
    assert duplicate.passed is False
    assert any(difference.path.endswith(".id") for difference in duplicate.differences)


def test_duplicate_mapping_path_is_a_contradiction_with_rule_provenance():
    mapping = copy.deepcopy(MAPPING)
    mapping["rules"].append(
        {
            **mapping["rules"][0],
            "rule_id": "resident-id-duplicate",
        }
    )

    report = compare_sedb_projection(EXPECTED, EXPECTED, mapping)

    assert report.passed is False
    assert report.counts == {
        "expected_by_mapping": 0,
        "unmapped": 0,
        "contradiction": 1,
    }
    assert report.differences[0].rule_id == "resident-id-duplicate"
