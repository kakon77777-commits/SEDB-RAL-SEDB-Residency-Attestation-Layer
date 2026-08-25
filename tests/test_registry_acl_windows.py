from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_registry_root import byte_map

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.registry_root import RegistryStorage, registry_root_status
from sedb_ral.registry_root_contracts import (
    APPROVED_ROOT_SCOPES,
    PRODUCTION_REGISTRY_PARENT,
    PRODUCTION_REGISTRY_ROOT,
    RegistryAclObservation,
    bind_document_digest,
    plan_registry_root,
    verify_registry_acl,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ACL test")
ROOT = Path(__file__).parents[1]
GET_ACL = ROOT / "scripts/Get-RegistryAclObservation.ps1"
INITIALIZE = ROOT / "scripts/Initialize-ProductionRegistry.ps1"
TIME_REF = "time:host-wall-clock-unverified:2026-08-25T12:00:00+08:00"


def powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is unavailable")
    return executable


def current_sid() -> str:
    result = subprocess.run(
        [
            powershell(),
            "-NoProfile",
            "-Command",
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def observe(path: Path, logical_root: str, owner_sid: str) -> dict[str, object]:
    result = subprocess.run(
        [
            powershell(),
            "-NoProfile",
            "-File",
            str(GET_ACL),
            "-Root",
            str(path),
            "-LogicalRoot",
            logical_root,
            "-ExpectedOwnerSid",
            owner_sid,
            "-TimeRef",
            TIME_REF,
            "-PythonExe",
            sys.executable,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def authority_for(plan: dict[str, object]) -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-root-authority/0.1",
            "authority_id": "authority:4e928ea1-0827-40d1-b6bf-47dc9cba1708",
            "operation_plan_digest": plan["plan_digest"],
            "exact_root": PRODUCTION_REGISTRY_ROOT,
            "scopes": list(APPROVED_ROOT_SCOPES),
            "status": "active",
            "issued_time_ref": TIME_REF,
            "authorization_basis": "direct_user_instruction",
            "expires_after_plan_completion": True,
            "not_claimed": [
                "resident_identity",
                "resident_registration",
                "private_access",
                "delete_authority",
            ],
        },
        "authority_digest",
    )


def write_json(path: Path, value: object) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path


def test_inherited_acl_observation_is_rejected_by_the_core(tmp_path):
    seed = tmp_path / "inherited"
    seed.mkdir()
    sid = current_sid()
    observation = observe(seed, PRODUCTION_REGISTRY_PARENT, sid)
    RegistryAclObservation.from_dict(observation)

    with pytest.raises(RALValidationError) as caught:
        verify_registry_acl(
            observation=observation,
            expected_root=PRODUCTION_REGISTRY_PARENT,
            expected_owner_sid=sid,
        )

    assert caught.value.code in {
        "registry_acl_inheritance_enabled",
        "registry_acl_required_access_missing",
        "registry_acl_broad_write",
    }


def test_initializer_protects_parent_and_candidate_then_publishes(tmp_path):
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    sid = current_sid()
    seed_observation = observe(storage_root, PRODUCTION_REGISTRY_PARENT, sid)
    plan = plan_registry_root(
        final_root=PRODUCTION_REGISTRY_ROOT,
        candidate_id="6f5121df-a649-49f3-a3f8-f1ef7df6f3af",
        source_commit="a" * 40,
        source_package_version="0.4.0",
        time_ref=TIME_REF,
        filesystem=seed_observation["filesystem"],
        volume_identity=seed_observation["volume_identity"],
        expected_owner_sid=sid,
    )
    authority = authority_for(plan)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    plan_path = write_json(inputs / "plan.json", plan)
    authority_path = write_json(inputs / "authority.json", authority)
    time_path = write_json(
        inputs / "time.json",
        {
            "schema": "sedb-ral.temporal-receipt/0.1",
            "time_ref": TIME_REF,
            "status": "host_wall_clock_unverified",
            "not_claimed": ["ctcl_registered", "third_party_time"],
        },
    )
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    command = [
        powershell(),
        "-NoProfile",
        "-File",
        str(INITIALIZE),
        "-FinalRoot",
        PRODUCTION_REGISTRY_ROOT,
        "-PlanFile",
        str(plan_path),
        "-AuthorityFile",
        str(authority_path),
        "-TimeReceiptFile",
        str(time_path),
        "-SyntheticStorageRoot",
        str(storage_root),
        "-OutputDirectory",
        str(outputs),
        "-PythonExe",
        sys.executable,
    ]

    result = subprocess.run(command, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    storage = RegistryStorage.synthetic(storage_root)
    assert storage.final.is_dir()
    for name, logical_root in (
        ("parent-acl.json", PRODUCTION_REGISTRY_PARENT),
        ("candidate-acl.json", plan["candidate_root"]),
        ("final-acl.json", PRODUCTION_REGISTRY_ROOT),
    ):
        observation = json.loads((outputs / name).read_text(encoding="utf-8"))
        verify_registry_acl(
            observation=observation,
            expected_root=logical_root,
            expected_owner_sid=sid,
        )
        assert observation["volume_identity"] == plan["volume_identity"]
    candidate_observation = json.loads(
        (outputs / "candidate-acl.json").read_text(encoding="utf-8")
    )
    final_observation = json.loads(
        (outputs / "final-acl.json").read_text(encoding="utf-8")
    )
    assert (
        candidate_observation["acl_fingerprint"] == final_observation["acl_fingerprint"]
    )
    status = registry_root_status(
        expected_plan_digest=plan["plan_digest"], storage=storage
    )
    assert status["verified"] is True
    assert status["resident_count"] == 0
    assert status["private_read_count"] == 0

    before = byte_map(storage.final)
    second_outputs = tmp_path / "second-outputs"
    second_outputs.mkdir()
    repeated = list(command)
    repeated[repeated.index(str(outputs))] = str(second_outputs)
    second = subprocess.run(repeated, text=True, capture_output=True, check=False)
    assert second.returncode != 0
    failure = json.loads((second_outputs / "failure.json").read_text(encoding="utf-8"))
    assert failure["schema"] == ("sedb-ral.registry-initialization-failure/0.1")
    assert failure["status"] == "failed"
    assert failure["cleanup_performed"] is False
    assert str(storage_root) not in json.dumps(failure)
    assert byte_map(storage.final) == before
