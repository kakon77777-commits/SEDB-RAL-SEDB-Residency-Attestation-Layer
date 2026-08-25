from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from phase3a_operations_helpers import (
    digest,
    synthetic_registry_status,
    valid_policy,
)

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.operations.models import OperationsPolicy
from sedb_ral.operations.workspace import (
    EXPECTED_WORKSPACE_DIRECTORIES,
    OperationsWorkspace,
    activate_policy,
    initialize_synthetic_workspace,
    plan_synthetic_workspace,
    verify_operations_workspace,
)

ROOT = Path(__file__).parents[1]
WORKSPACE_ID = "6f5121df-a649-49f3-a3f8-f1ef7df6f3af"
TIME_REF = "time:synthetic-unavailable:r3b-a-workspace"


def workspace_plan(target: Path, **status_overrides: object):
    return plan_synthetic_workspace(
        registry_status=synthetic_registry_status(**status_overrides),
        policy=OperationsPolicy.from_dict(valid_policy()),
        workspace_id=WORKSPACE_ID,
        time_ref=TIME_REF,
        target=target,
    )


def initialized(tmp_path: Path) -> tuple[OperationsWorkspace, dict[str, object]]:
    status = synthetic_registry_status()
    policy = OperationsPolicy.from_dict(valid_policy())
    plan = plan_synthetic_workspace(
        registry_status=status,
        policy=policy,
        workspace_id=WORKSPACE_ID,
        time_ref=TIME_REF,
        target=tmp_path / "operations",
    )
    return initialize_synthetic_workspace(plan, policy), status


def test_synthetic_workspace_has_exact_initial_layout_and_bound_manifest(tmp_path):
    workspace, status = initialized(tmp_path)

    directories = {
        path.relative_to(workspace.root).as_posix()
        for path in workspace.root.rglob("*")
        if path.is_dir()
    }
    assert directories == EXPECTED_WORKSPACE_DIRECTORIES
    assert {
        path.relative_to(workspace.root).as_posix()
        for path in workspace.root.rglob("*")
        if path.is_file()
    } == {
        "OPERATIONS-MANIFEST.json",
        "active-policy/00000000000000000000.json",
        next(
            path.relative_to(workspace.root).as_posix()
            for path in (workspace.root / "policies").iterdir()
        ),
    }
    manifest = workspace.manifest.to_dict()
    assert manifest["registry_id"] == status["registry_id"]
    assert manifest["registry_manifest_digest"] == status["manifest_digest"]
    assert manifest["registry_control_digest"] == status["control_digest"]
    assert manifest["registry_source_tree_digest"] == status["tree_digest"]
    assert manifest["synthetic_only"] is True
    assert manifest["production_activation"] is False


@pytest.mark.parametrize(
    ("target", "code"),
    [
        (
            Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"),
            "operations_production_activation_not_authorized",
        ),
        (
            Path(r"D:\AI_RESIDENCE\AI_HOME\00_RESIDENCE\agents\example"),
            "operations_private_boundary",
        ),
    ],
)
def test_production_or_private_target_refuses_before_creation(target, code):
    with pytest.raises(RALValidationError) as caught:
        workspace_plan(target)

    assert caught.value.code == code


def test_git_checkout_target_refuses_before_creation():
    target = ROOT / "must-not-create-operations"

    with pytest.raises(RALValidationError) as caught:
        workspace_plan(target)

    assert caught.value.code == "operations_git_boundary"
    assert not target.exists()


def test_existing_target_is_preserved_and_refused(tmp_path):
    target = tmp_path / "operations"
    target.mkdir()
    marker = target / "preserve.bin"
    marker.write_bytes(b"preserve")
    plan = workspace_plan(target)

    with pytest.raises(RALValidationError) as caught:
        initialize_synthetic_workspace(plan, OperationsPolicy.from_dict(valid_policy()))

    assert caught.value.code == "operations_workspace_exists"
    assert marker.read_bytes() == b"preserve"


def test_registry_binding_drift_refuses_workspace_verification(tmp_path):
    workspace, status = initialized(tmp_path)
    changed = {**status, "manifest_digest": digest("f")}

    with pytest.raises(RALValidationError) as caught:
        verify_operations_workspace(
            workspace.root,
            expected_generation=workspace.manifest.to_dict()["operations_generation"],
            registry_status=changed,
        )

    assert caught.value.code == "operations_registry_binding_mismatch"


def test_policy_byte_mutation_turns_verification_red(tmp_path):
    workspace, status = initialized(tmp_path)
    policy_path = next((workspace.root / "policies").iterdir())
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    value["lease_seconds"] = 61
    policy_path.write_bytes(canonical_bytes(value))

    with pytest.raises(RALValidationError) as caught:
        verify_operations_workspace(
            workspace.root,
            expected_generation=workspace.manifest.to_dict()["operations_generation"],
            registry_status=status,
        )

    assert caught.value.code == "operations_policy_digest_mismatch"


def test_unexpected_top_level_file_is_refused(tmp_path):
    workspace, status = initialized(tmp_path)
    (workspace.root / "unexpected.txt").write_bytes(b"unexpected")

    with pytest.raises(RALValidationError) as caught:
        verify_operations_workspace(
            workspace.root,
            expected_generation=workspace.manifest.to_dict()["operations_generation"],
            registry_status=status,
        )

    assert caught.value.code == "operations_workspace_layout_mismatch"


def test_policy_activation_is_append_only_and_sequence_bound(tmp_path):
    workspace, status = initialized(tmp_path)
    second = OperationsPolicy.from_dict(valid_policy(policy_version="2"))

    receipt = activate_policy(workspace, second, expected_active_sequence=0)

    assert receipt["control_sequence"] == 1
    assert receipt["policy_digest"] == second.digest
    assert (workspace.root / "active-policy/00000000000000000001.json").is_file()
    verify_operations_workspace(
        workspace.root,
        expected_generation=workspace.manifest.to_dict()["operations_generation"],
        registry_status=status,
    )
    with pytest.raises(RALValidationError) as caught:
        activate_policy(workspace, second, expected_active_sequence=0)
    assert caught.value.code == "operations_policy_sequence_mismatch"


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse privilege varies")
def test_reparse_point_inside_workspace_is_refused_when_available(tmp_path):
    workspace, status = initialized(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.root / "inbox" / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")

    with pytest.raises(RALValidationError) as caught:
        verify_operations_workspace(
            workspace.root,
            expected_generation=workspace.manifest.to_dict()["operations_generation"],
            registry_status=status,
        )
    assert caught.value.code == "operations_workspace_reparse_point"
