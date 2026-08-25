from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = (
    ROOT / "scripts/Get-RegistryAclObservation.ps1",
    ROOT / "scripts/Initialize-ProductionRegistry.ps1",
)


def powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is unavailable")
    return executable


@pytest.mark.parametrize("script", SCRIPTS)
def test_registry_acl_scripts_parse_without_errors_or_destructive_commands(script):
    command = r"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:SEDB_RAL_SCRIPT, [ref]$tokens, [ref]$errors
)
$commands = @(
  $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst]
  }, $true) | ForEach-Object { $_.GetCommandName() }
)
[ordered]@{
  errors = @($errors | ForEach-Object { $_.Message })
  commands = $commands
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [powershell(), "-NoProfile", "-Command", command],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env={**os.environ, "SEDB_RAL_SCRIPT": str(script)},
    )

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["errors"] == []
    commands = {str(value).casefold() for value in parsed["commands"] if value}
    assert commands.isdisjoint(
        {
            "remove-item",
            "move-item",
            "invoke-webrequest",
            "invoke-restmethod",
            "start-process",
        }
    )
