import json
import sys
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
    assert manifest["fixture_paths"] == [
        "positive/resident-address.json",
        "negative/shared-runtime-tag.json",
        "mixed_population/one-resident.json",
    ]
    assert manifest["required_decisions"] == [
        "admit",
        "reject",
        "indeterminate",
    ]
    decisions = {
        evaluate_identifier_fixture(load(relative)).decision.value
        for relative in manifest["fixture_paths"]
    }
    assert decisions == set(manifest["required_decisions"])


def test_subject_kind_must_match_discrimination_target():
    fixture = load("positive/resident-address.json")
    fixture["identifier_exemplar"]["subject_kind"] = "runtime"
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


def test_cross_resident_collision_rejects_before_sample_sufficiency():
    fixture = load("negative/shared-runtime-tag.json")
    seen_residents = set()
    fixture["observations"] = [
        observation
        for observation in fixture["observations"]
        if not (
            observation["resident_ref"] in seen_residents
            or seen_residents.add(observation["resident_ref"])
        )
    ]
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("does_not_distinguish_residents",)


def test_within_resident_instability_rejects_before_population_sufficiency():
    fixture = load("mixed_population/one-resident.json")
    fixture["observations"][1]["observed_value"] = (
        "agent://example/resident/only-rotated"
    )
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("unstable_within_resident",)


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
    fixture["identifier_exemplar"]["seat"] = "overloaded"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    assert main(["identifier", "check", str(path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "reject"
    assert output["reason_codes"] == ["schema_invalid"]


def test_identifier_check_cli_maps_missing_input_to_typed_exit_one(
    tmp_path, capsys
):
    path = tmp_path / "missing.json"
    assert main(["identifier", "check", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "error"
    assert output["reason_codes"] == ["input_unreadable"]


def test_identifier_check_cli_maps_invalid_json_to_typed_exit_one(
    tmp_path, capsys
):
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    assert main(["identifier", "check", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "error"
    assert output["reason_codes"] == ["input_invalid_json"]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ('{"a":1,"a":2}', "duplicate_key"),
        ('{"a":1.5}', "unsupported_number"),
    ],
)
def test_identifier_check_cli_types_strict_json_contract_errors(
    tmp_path, capsys, payload, reason
):
    path = tmp_path / "strict-invalid.json"
    path.write_text(payload, encoding="utf-8")
    assert main(["identifier", "check", str(path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "reject"
    assert output["reason_codes"] == [reason]


def test_identifier_check_cli_maps_invalid_utf8_to_typed_exit_one(
    tmp_path, capsys
):
    path = tmp_path / "invalid-utf8.json"
    path.write_bytes(b"\xff")
    assert main(["identifier", "check", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["reason_codes"] == ["input_not_utf8"]


def test_identifier_check_cli_maps_directory_input_to_typed_exit_one(
    tmp_path, capsys
):
    assert main(["identifier", "check", str(tmp_path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["reason_codes"] == ["input_unreadable"]


def test_identifier_check_cli_emits_exact_canonical_utf8_lf(capfd):
    path = ROOT / "negative/shared-runtime-tag.json"
    assert main(["identifier", "check", str(path)]) == 2
    captured = capfd.readouterr()
    assert captured.err == ""
    assert captured.out.encode(sys.stdout.encoding or "utf-8") == (
        b'{"decision":"reject","distinct_residents":2,'
        b'"distinct_values":1,'
        b'"reason_codes":["does_not_distinguish_residents"]}\n'
    )


@pytest.mark.parametrize("field", ["namespace", "identifier_kind"])
def test_observations_must_match_exemplar_contract(field):
    fixture = load("positive/resident-address.json")
    fixture["observations"][0][field] = "unrelated"
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("observation_contract_mismatch",)


def test_exemplar_value_must_appear_in_observations():
    fixture = load("positive/resident-address.json")
    fixture["identifier_exemplar"]["value"] = (
        "agent://example/resident/unobserved"
    )
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("identifier_exemplar_unobserved",)


def test_duplicate_observation_id_is_rejected_even_when_rows_differ():
    fixture = load("positive/resident-address.json")
    fixture["observations"][1]["observation_id"] = fixture[
        "observations"
    ][0]["observation_id"]
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("observation_id_collision",)


def test_instance_cannot_claim_two_residents():
    fixture = load("positive/resident-address.json")
    fixture["observations"][2]["instance_ref"] = fixture[
        "observations"
    ][0]["instance_ref"]
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("instance_resident_conflict",)


def test_instance_cannot_claim_two_runtimes():
    fixture = load("positive/resident-address.json")
    fixture["observations"][1]["instance_ref"] = fixture[
        "observations"
    ][0]["instance_ref"]
    fixture["observations"][1]["runtime_ref"] = "runtime:other"
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("instance_runtime_conflict",)


def test_different_runtime_per_resident_cannot_support_admit():
    fixture = load("positive/resident-address.json")
    for observation in fixture["observations"]:
        observation["runtime_ref"] = (
            "runtime:alpha"
            if observation["resident_ref"] == "resident:alice"
            else "runtime:beta"
        )
        observation["observed_value"] = (
            "runtime-tag:alpha"
            if observation["runtime_ref"] == "runtime:alpha"
            else "runtime-tag:beta"
        )
    fixture["identifier_exemplar"]["value"] = "runtime-tag:alpha"
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.INDETERMINATE
    assert result.reason_codes == ("same_runtime_population_unmeasured",)


def test_nfc_equivalent_observed_values_cannot_appear_distinct():
    fixture = load("positive/resident-address.json")
    fixture["identifier_exemplar"]["value"] = "é"
    for observation in fixture["observations"]:
        observation["observed_value"] = (
            "é"
            if observation["resident_ref"] == "resident:alice"
            else "e\u0301"
        )
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("does_not_distinguish_residents",)


def test_nfc_equivalent_instance_refs_count_once():
    fixture = load("positive/resident-address.json")
    fixture["observations"][0]["instance_ref"] = "instance:alice:é"
    fixture["observations"][1]["instance_ref"] = "instance:alice:e\u0301"
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.INDETERMINATE
    assert result.reason_codes == ("instances_per_resident_unmeasured",)


def test_nfc_equivalent_resident_refs_count_once():
    fixture = load("positive/resident-address.json")
    for observation in fixture["observations"]:
        observation["resident_ref"] = (
            "resident:é"
            if observation["resident_ref"] == "resident:alice"
            else "resident:e\u0301"
        )
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("unstable_within_resident",)
