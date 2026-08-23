import json
import shutil
from pathlib import Path

from sedb_ral.cli import main
from sedb_ral.ledger import append_event
from sedb_ral.phase1a import validate_phase1a

ROOT = Path(__file__).parents[1]
CTCL = json.loads(
    (ROOT / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)


def copy_gate_inputs(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(
        ROOT / "src/sedb_ral/schemas",
        target / "src/sedb_ral/schemas",
    )
    shutil.copytree(ROOT / "fixtures", target / "fixtures")
    return target


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_repository_phase1a_gate_is_green():
    report = validate_phase1a(ROOT)
    assert report.passed is True
    assert set(report.observed_decisions) == {
        "admit",
        "reject",
        "indeterminate",
    }
    assert report.error_codes == ()
    assert report.ledger_status == "checkpoint_verified"


def test_missing_negative_fixture_turns_gate_red(tmp_path):
    target = copy_gate_inputs(tmp_path)
    (target / "fixtures/identifier/negative/shared-runtime-tag.json").unlink()
    report = validate_phase1a(target)
    assert report.passed is False
    assert "negative_fixture_missing" in report.error_codes


def test_missing_positive_control_turns_gate_red(tmp_path):
    target = copy_gate_inputs(tmp_path)
    (target / "fixtures/identifier/positive/resident-address.json").unlink()
    report = validate_phase1a(target)
    assert report.passed is False
    assert "positive_fixture_missing" in report.error_codes


def test_manifest_cannot_drop_a_fixture_class(tmp_path):
    target = copy_gate_inputs(tmp_path)
    path = target / "fixtures/identifier/mixed_population/manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["fixture_paths"].remove("negative/shared-runtime-tag.json")
    value["required_decisions"].remove("reject")
    path.write_text(json.dumps(value), encoding="utf-8")
    report = validate_phase1a(target)
    assert report.passed is False
    assert "fixture_manifest_mismatch" in report.error_codes


def test_promoted_ctcl_reading_turns_gate_red(tmp_path):
    target = copy_gate_inputs(tmp_path)
    path = target / "fixtures/ctcl/reading.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["retrievability"] = {
        "expected": True,
        "status": "verified",
        "checked_at_ref": "ctcl:instant:invalid-promotion",
        "retrieval_evidence_ref": "evidence:invalid-promotion",
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    report = validate_phase1a(target)
    assert report.passed is False
    assert "reading_not_retrievable" in report.error_codes


def test_broken_ledger_draft_turns_gate_red(tmp_path):
    target = copy_gate_inputs(tmp_path)
    path = target / "fixtures/ledger/event-002.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["causal_parent_ids"] = ["evt_missing"]
    path.write_text(json.dumps(value), encoding="utf-8")
    report = validate_phase1a(target)
    assert report.passed is False
    assert "causal_parent_missing" in report.error_codes


def test_canonicalize_cli_emits_exact_bytes(tmp_path, capfd):
    path = tmp_path / "value.json"
    path.write_text('{"b":"e\\u0301","a":1}', encoding="utf-8")
    assert main(["canonicalize", str(path)]) == 0
    captured = capfd.readouterr()
    assert captured.err == ""
    assert captured.out.encode("utf-8") == '{"a":1,"b":"é"}\n'.encode(
        "utf-8"
    )


def test_contract_validate_cli_is_deterministic(capsys):
    fixture = ROOT / "fixtures/identifier/positive/resident-address.json"
    assert (
        main(
            [
                "contract",
                "validate",
                "identifier-discrimination.schema.json",
                str(fixture),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "contract": "identifier-discrimination.schema.json",
        "valid": True,
    }


def test_ledger_verify_requires_an_expected_head(tmp_path, capsys):
    draft = load("fixtures/ledger/event-001.json")
    receipt = append_event(
        tmp_path,
        draft,
        CTCL,
        expected_previous_chain_digest=None,
    )
    assert main(["ledger", "verify", str(tmp_path)]) == 3
    without_head = json.loads(capsys.readouterr().out)
    assert without_head["status"] == "internally_consistent"
    assert without_head["valid"] is False

    assert (
        main(
            [
                "ledger",
                "verify",
                str(tmp_path),
                "--expected-final-chain-digest",
                receipt.chain_digest,
            ]
        )
        == 0
    )
    with_head = json.loads(capsys.readouterr().out)
    assert with_head["status"] == "checkpoint_verified"
    assert with_head["valid"] is True


def test_phase1a_cli_and_standalone_gate_match(capsys):
    assert main(["phase1a", "verify", str(ROOT)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == validate_phase1a(ROOT).as_json()
