import json
from pathlib import Path

import pytest

from sedb_ral.cli import main
from sedb_ral.identifier import (
    DiscriminationDecision,
    evaluate_identifier_fixture,
)

ROOT = Path(__file__).parents[1] / "fixtures" / "identifier"


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("relative", "decision", "reason"),
    [
        (
            "positive/resident-address.json",
            DiscriminationDecision.ADMIT,
            "admissible_resident_discriminator",
        ),
        (
            "negative/shared-runtime-tag.json",
            DiscriminationDecision.REJECT,
            "does_not_distinguish_residents",
        ),
        (
            "mixed_population/one-resident.json",
            DiscriminationDecision.INDETERMINATE,
            "population_too_small",
        ),
    ],
)
def test_expected_fixture_decisions(relative, decision, reason):
    fixture = load(relative)
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is decision
    assert reason in result.reason_codes
    assert result.decision.value == fixture["expected_decision"]
    assert set(result.reason_codes) == set(fixture["expected_reason_codes"])


def test_mixed_population_has_discriminating_power():
    manifest = load("mixed_population/manifest.json")
    decisions = {
        evaluate_identifier_fixture(load(relative)).decision.value
        for relative in manifest["fixture_paths"]
    }
    assert decisions == set(manifest["required_decisions"])


def test_subject_kind_must_match_discrimination_target():
    fixture = load("positive/resident-address.json")
    fixture["identifier"]["subject_kind"] = "runtime"
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("identifier_subject_mismatch",)


def test_unmeasured_instance_population_is_indeterminate():
    fixture = load("positive/resident-address.json")
    fixture["observations"] = [
        fixture["observations"][0],
        fixture["observations"][2],
    ]
    fixture["expected_decision"] = "indeterminate"
    fixture["expected_reason_codes"] = [
        "instances_per_resident_unmeasured"
    ]
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.INDETERMINATE
    assert result.reason_codes == ("instances_per_resident_unmeasured",)


def test_value_instability_within_resident_is_rejected():
    fixture = load("positive/resident-address.json")
    fixture["observations"][1]["observed_value"] = (
        "agent://example/resident/alice-rotated"
    )
    fixture["expected_decision"] = "reject"
    fixture["expected_reason_codes"] = ["unstable_within_resident"]
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("unstable_within_resident",)


@pytest.mark.parametrize(
    ("relative", "exit_code", "decision"),
    [
        ("positive/resident-address.json", 0, "admit"),
        ("negative/shared-runtime-tag.json", 2, "reject"),
        ("mixed_population/one-resident.json", 3, "indeterminate"),
    ],
)
def test_identifier_check_cli_exit_codes(
    relative, exit_code, decision, capsys
):
    assert main(["identifier", "check", str(ROOT / relative)]) == exit_code
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == decision
    assert set(output) == {
        "decision",
        "reason_codes",
        "distinct_residents",
        "distinct_values",
    }


def test_identifier_check_cli_maps_schema_error_to_exit_two(tmp_path, capsys):
    fixture = load("positive/resident-address.json")
    fixture["identifier"]["seat"] = "overloaded"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    assert main(["identifier", "check", str(path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "reject"
    assert output["reason_codes"] == ["schema_invalid"]
