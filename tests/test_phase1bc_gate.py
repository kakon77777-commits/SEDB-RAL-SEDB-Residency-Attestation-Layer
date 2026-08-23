import json
import shutil
from pathlib import Path

from sedb_ral.cli import main
import sedb_ral.phase1bc as phase1bc
from sedb_ral.phase1bc import validate_phase1bc

ROOT = Path(__file__).parents[1]


def test_repository_phase1bc_gate_is_green_and_executes_fault_controls():
    report = validate_phase1bc(ROOT)

    assert report.passed is True
    assert report.error_codes == ()
    assert report.phase1a_passed is True
    assert report.no_send_findings == ()
    assert report.sqlite_bytes_identical is True
    assert [
        (
            item.test_name,
            item.expected_red_code,
            item.observed_red_code,
            item.executed,
        )
        for item in report.executed_faults
    ] == [
        (
            "phase1a_missing_negative_fixture",
            "negative_fixture_missing",
            "negative_fixture_missing",
            True,
        ),
        (
            "sqlite_projection_mutation",
            "sqlite_projection_mismatch",
            "sqlite_projection_mismatch",
            True,
        ),
        (
            "no_send_socket_call",
            "forbidden_call:socket.create_connection",
            "forbidden_call:socket.create_connection",
            True,
        ),
        (
            "no_send_sedb_import",
            "forbidden_import:sedb",
            "forbidden_import:sedb",
            True,
        ),
    ]


def test_phase1bc_cli_matches_integrated_report(capsys):
    assert main(["phase1bc", "verify", str(ROOT)]) == 0

    assert json.loads(capsys.readouterr().out) == validate_phase1bc(ROOT).as_json()


def test_phase1bc_cli_reports_a_corrupted_repository_red(tmp_path, capsys):
    copied = tmp_path / "repo"
    shutil.copytree(ROOT / "src/sedb_ral", copied / "src/sedb_ral")
    shutil.copytree(ROOT / "fixtures", copied / "fixtures")
    shutil.copytree(ROOT / "corpus", copied / "corpus")
    (copied / "fixtures/identifier/negative/shared-runtime-tag.json").unlink()

    assert main(["phase1bc", "verify", str(copied)]) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert report["phase1a_passed"] is False
    assert "phase1a_gate_failed" in report["error_codes"]


def test_phase1bc_retains_completed_faults_when_later_fault_raises(monkeypatch):
    original = phase1bc._fault_no_send

    def fail_only_late_fault(name: str, source: str, expected: str):
        if name == "no_send_sedb_import":
            raise RuntimeError("late fault control failed")
        return original(name, source, expected)

    monkeypatch.setattr(phase1bc, "_fault_no_send", fail_only_late_fault)

    report = validate_phase1bc(ROOT)

    assert report.passed is False
    assert "phase1bc_gate_error" in report.error_codes
    assert [item.test_name for item in report.executed_faults] == [
        "phase1a_missing_negative_fixture",
        "sqlite_projection_mutation",
        "no_send_socket_call",
    ]


def test_new_cli_groups_only_read_inputs_and_write_temp_projections(tmp_path, capsys):
    application = ROOT / "fixtures/application/authorized-zero-address.json"
    assert main(["application", "check", str(application)]) == 3
    application_result = json.loads(capsys.readouterr().out)
    assert application_result["decision"] == "defer"
    assert application_result["reason_codes"] == ["authority_authorship_unverified"]

    events = tmp_path / "events.json"
    events.write_text("[]", encoding="utf-8")
    assert main(["project", "rebuild", str(events)]) == 0
    assert json.loads(capsys.readouterr().out)["projection_meta"] == 4

    claim = json.loads(
        application.read_text(encoding="utf-8")
    )["application"]["claims"][0]
    claim_events = tmp_path / "claim-events.json"
    claim_events.write_text(
        json.dumps(
            [
                {
                    "ledger_seq": 1,
                    "event_id": "evt_claim",
                    "event_type": "claim.recorded",
                    "payload": {"claim": claim},
                },
                {
                    "ledger_seq": 2,
                    "event_id": "evt_attestation",
                    "event_type": "attestation.recorded",
                    "payload": {
                        "attestation": {
                            "schema_version": "0.1",
                            "attestation_id": "attestation:test:1",
                            "claim_ref": "claim:test:1",
                            "evidence_basis": "own_execution",
                            "evidence_root_refs": ["evidence:test:1"],
                            "derivation_parent_refs": [],
                            "independence_status": "independent",
                            "verification_status": "verified",
                        }
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    assert main(["explain", "claim", str(claim_events), "claim:test:1"]) == 0
    assert json.loads(capsys.readouterr().out)["distinct_root_count"] == 1

    observation = ROOT / "fixtures/adapters/codex-queue/materialized-and-acknowledged.json"
    assert main(["diagnose", "delivery", str(observation)]) == 0
    assert json.loads(capsys.readouterr().out)["stage"] == "instance_acknowledged"
