from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/Initialize-ProductionOperationsExtension.ps1"


def test_action_script_refuses_wrong_root_before_reading_inputs(tmp_path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh unavailable")
    result = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-FinalRoot",
            r"D:\wrong",
            "-PlanFile",
            str(tmp_path / "missing-plan.json"),
            "-AuthorityFile",
            str(tmp_path / "missing-authority.json"),
            "-PreCheckpointFile",
            str(tmp_path / "missing-checkpoint.json"),
            "-OutputDirectory",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "production_operations_activation_failed" in result.stderr

