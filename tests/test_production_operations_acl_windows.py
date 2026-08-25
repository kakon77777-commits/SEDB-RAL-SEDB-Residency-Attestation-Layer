from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.production_operations_contracts import (
    default_dormant_policy,
    plan_production_operations_extension,
)
from sedb_ral.registry_root import registry_root_status
from production_operations_helpers import CANDIDATE_ID, GENERATION, TIME_REF, authority_value, digest
from test_production_operations_layout import published_storage


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ACL test")
ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/Initialize-ProductionOperationsExtension.ps1"
GET_ACL = ROOT / "scripts/Get-RegistryAclObservation.ps1"
LOGICAL_CANDIDATE = rf"D:\AI_RESIDENCE\REGISTRY\.SEDB-RAL.operations-{CANDIDATE_ID}"


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


def protect(path: Path, owner_sid: str) -> None:
    command = rf'''
$owner=[System.Security.Principal.SecurityIdentifier]::new("{owner_sid}")
$security=[System.Security.AccessControl.DirectorySecurity]::new()
$security.SetOwner($owner)
$security.SetAccessRuleProtection($true,$false)
$inheritance=[System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
foreach($sid in @("{owner_sid}","S-1-5-18","S-1-5-32-544")){{
  $identity=[System.Security.Principal.SecurityIdentifier]::new($sid)
  $rule=[System.Security.AccessControl.FileSystemAccessRule]::new($identity,[System.Security.AccessControl.FileSystemRights]::FullControl,$inheritance,[System.Security.AccessControl.PropagationFlags]::None,[System.Security.AccessControl.AccessControlType]::Allow)
  [void]$security.AddAccessRule($rule)
}}
Set-Acl -LiteralPath "{path}" -AclObject $security
'''
    subprocess.run(
        [powershell(), "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        check=True,
    )


def observe(path: Path, owner_sid: str) -> dict[str, object]:
    result = subprocess.run(
        [
            powershell(),
            "-NoProfile",
            "-File",
            str(GET_ACL),
            "-Root",
            str(path),
            "-LogicalRoot",
            LOGICAL_CANDIDATE,
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
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_bytes(canonical_bytes(value))


def test_windows_wrapper_publishes_only_dormant_synthetic_extension(
    published_storage, tmp_path
):
    owner = current_sid()
    probe = tmp_path / "acl-probe"
    probe.mkdir()
    protect(probe, owner)
    acl = observe(probe, owner)
    status = registry_root_status(storage=published_storage)
    policy = default_dormant_policy()
    plan = plan_production_operations_extension(
        registry_status=status,
        candidate_id=CANDIDATE_ID,
        operations_generation=GENERATION,
        policy_digest=policy["policy_digest"],
        source_commit="2470be770962556998925a739c3d1099dc830786",
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity=acl["volume_identity"],
        expected_owner_sid=owner,
        acl_fingerprint=acl["acl_fingerprint"],
        pre_checkpoint_digest=digest("3"),
        time_ref=TIME_REF,
    )
    authority = authority_value(plan["plan_digest"])
    action = tmp_path / "action"
    action.mkdir()
    plan_path = action / "plan.json"
    authority_path = action / "authority.json"
    checkpoint_path = action / "checkpoint.json"
    write_json(plan_path, plan)
    write_json(authority_path, authority)
    write_json(checkpoint_path, {"checkpoint_digest": plan["pre_checkpoint_digest"]})

    result = subprocess.run(
        [
            powershell(),
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-FinalRoot",
            r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL",
            "-PlanFile",
            str(plan_path),
            "-AuthorityFile",
            str(authority_path),
            "-PreCheckpointFile",
            str(checkpoint_path),
            "-OutputDirectory",
            str(action),
            "-SyntheticStorageRoot",
            str(published_storage.parent.parent),
            "-PythonExe",
            sys.executable,
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )

    assert result.returncode == 0, result.stderr
    final = registry_root_status(storage=published_storage)
    assert final["extensions_status"] == "active_dormant"
    assert final["ledger_event_count"] == 0
    assert final["resident_count"] == 0
