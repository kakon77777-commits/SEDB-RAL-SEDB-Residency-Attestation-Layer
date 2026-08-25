from __future__ import annotations

import json
from pathlib import Path

import pytest
from phase3a_operations_helpers import (
    synthetic_registry_status,
    valid_intake,
    valid_operation_request,
    valid_policy,
)
from test_limen_public_view_cli import committed_ledger

from sedb_ral.canonical import canonical_bytes
from sedb_ral.cli import main
from sedb_ral.operations.workspace import plan_synthetic_workspace


def write_json(path: Path, value: object) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path


def test_operations_init_verify_intake_request_status_round_trip(tmp_path, capfd):
    status = synthetic_registry_status()
    policy = valid_policy()
    target = tmp_path / "operations"
    plan = plan_synthetic_workspace(
        registry_status=status,
        policy=__import__(
            "sedb_ral.operations.models", fromlist=["OperationsPolicy"]
        ).OperationsPolicy.from_dict(policy),
        workspace_id="6f5121df-a649-49f3-a3f8-f1ef7df6f3af",
        time_ref="time:synthetic-unavailable:cli",
        target=target,
    )
    plan_path = write_json(tmp_path / "plan.json", plan)
    policy_path = write_json(tmp_path / "policy.json", policy)
    status_path = write_json(tmp_path / "status.json", status)

    assert main(["operations", "init-synthetic", str(plan_path), str(policy_path)]) == 0
    initialized = json.loads(capfd.readouterr().out)
    assert initialized["initialized"] is True
    generation = initialized["operations_generation"]

    assert (
        main(
            [
                "operations",
                "verify",
                str(target),
                "--expected-generation",
                generation,
                "--registry-status",
                str(status_path),
            ]
        )
        == 0
    )
    assert json.loads(capfd.readouterr().out)["verified"] is True

    intake_path = write_json(tmp_path / "intake.json", valid_intake())
    request = valid_operation_request(operation_id="operation:cli-status")
    request_path = write_json(tmp_path / "request.json", request)
    assert (
        main(["operations", "intake-add", str(intake_path), "--root", str(target)]) == 0
    )
    capfd.readouterr()
    assert (
        main(["operations", "request-add", str(request_path), "--root", str(target)])
        == 0
    )
    capfd.readouterr()
    assert (
        main(["operations", "status", "operation:cli-status", "--root", str(target)])
        == 0
    )
    assert json.loads(capfd.readouterr().out)["state"] == "received"


def test_operations_export_public_cli_matches_core_file(tmp_path, capfd):
    ledger, head, _ = committed_ledger(tmp_path)
    output = tmp_path / "view.json"

    code = main(
        [
            "operations",
            "export-public",
            "--ledger-root",
            str(ledger),
            "--expected-head",
            head,
            "--sequence",
            "4",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    receipt = json.loads(capfd.readouterr().out)
    assert receipt["fabric_events"] == 0
    assert output.is_file()


@pytest.mark.parametrize(
    "command",
    [
        "init-synthetic",
        "verify",
        "intake-add",
        "request-add",
        "plan",
        "execute",
        "status",
        "export-public",
    ],
)
def test_operations_commands_require_explicit_inputs(command, capfd):
    assert main(["operations", command]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == ["cli_usage_error"]
