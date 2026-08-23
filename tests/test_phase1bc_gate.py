import json
import shutil
from pathlib import Path

from sedb_ral.cli import main
import sedb_ral.phase1bc as phase1bc
from sedb_ral.phase1bc import validate_phase1bc

ROOT = Path(__file__).parents[1]


def copy_required_inputs(tmp_path: Path) -> Path:
    copied = tmp_path / "repo"
    for relative in phase1bc.required_phase1bc_artifacts():
        source = ROOT / relative
        destination = copied / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return copied


def test_repository_phase1bc_gate_is_green_and_executes_fault_controls():
    report = validate_phase1bc(ROOT)

    assert report.passed is True
    assert report.error_codes == ()
    assert report.phase1a_passed is True
    assert report.no_send_findings == ()
    assert report.sqlite_bytes_identical is True
    assert report.incident_count == 29
    assert report.incident_sha256 == (
        "9a4a504621d6837b0724cbfebc7a9db84a5f260103d9ce585a3087a39a6a3828"
    )
    assert report.required_artifact_count == len(
        phase1bc.required_phase1bc_artifacts()
    )
    assert [
        (
            item.test_name,
            item.expected_red_code,
            item.observed_red_code,
            item.executed,
        )
        for item in report.executed_positive_controls
    ] == [
        ("admission_positive", "positive", "positive", True),
        ("projection_correction_positive", "positive", "positive", True),
        ("claim_explanation_positive", "positive", "positive", True),
        ("transcript_binding_positive", "positive", "positive", True),
        ("adapter_matrix_delivery_positive", "positive", "positive", True),
        ("sqlite_projection_positive", "positive", "positive", True),
        ("no_send_positive", "positive", "positive", True),
    ]
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
            "required_transcript_schema_missing",
            "required_artifact_missing:src/sedb_ral/schemas/transcript-binding.schema.json",
            "required_artifact_missing:src/sedb_ral/schemas/transcript-binding.schema.json",
            True,
        ),
        (
            "admission_cross_resident",
            "application_claim_subject_mismatch",
            "application_claim_subject_mismatch",
            True,
        ),
        (
            "projection_wrong_correction_target",
            "correction_target_event_mismatch",
            "correction_target_event_mismatch",
            True,
        ),
        (
            "claim_explanation_scope_mismatch",
            "scope_overlap_missing",
            "scope_overlap_missing",
            True,
        ),
        (
            "transcript_unbound_turn",
            "speaker_resolution_indeterminate",
            "speaker_resolution_indeterminate",
            True,
        ),
        (
            "adapter_matrix_invalid_submit",
            "schema_invalid",
            "schema_invalid",
            True,
        ),
        (
            "sqlite_projection_mutation",
            "sqlite_projection_mismatch",
            "sqlite_projection_mismatch",
            True,
        ),
        (
            "no_send_package_missing",
            "package_root_missing",
            "package_root_missing",
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
    copied = copy_required_inputs(tmp_path)
    (copied / "fixtures/identifier/negative/shared-runtime-tag.json").unlink()

    assert main(["phase1bc", "verify", str(copied)]) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert report["phase1a_passed"] is False
    assert "phase1a_gate_failed" in report["error_codes"]


def test_required_artifact_census_is_subset_based_and_transcript_schema_is_required(
    tmp_path,
):
    copied = copy_required_inputs(tmp_path)
    extra = copied / "src/sedb_ral/schemas/future-phase2.schema.json"
    extra.write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"$id":"https://example.test/future","type":"object"}',
        encoding="utf-8",
    )
    assert validate_phase1bc(copied).passed is True

    (copied / "src/sedb_ral/schemas/transcript-binding.schema.json").unlink()
    report = validate_phase1bc(copied)
    assert report.passed is False
    assert (
        "required_artifact_missing:src/sedb_ral/schemas/transcript-binding.schema.json"
        in report.error_codes
    )


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
        "required_transcript_schema_missing",
        "admission_cross_resident",
        "projection_wrong_correction_target",
        "claim_explanation_scope_mismatch",
        "transcript_unbound_turn",
        "adapter_matrix_invalid_submit",
        "sqlite_projection_mutation",
        "no_send_package_missing",
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
                            "evidence_refs": ["evidence:test:1"],
                            "record_status": "active",
                            "observer_independence_status": "independent",
                            "evidence_independence_status": "independent",
                            "independence_scope": "resident:test",
                            "verification_status": "verified",
                            "scope": ["resident:test"],
                            "temporal_validity": "valid",
                            "not_claimed": [],
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
