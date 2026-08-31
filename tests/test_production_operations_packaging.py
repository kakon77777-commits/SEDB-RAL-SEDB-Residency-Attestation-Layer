from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tomllib
import zipfile

import pytest

from sedb_ral import __version__
from sedb_ral.phase3a_operations import validate_phase3a_operations


ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    output = tmp_path_factory.mktemp("r3b-b-wheel")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_current_candidate_version_is_0_5_0c1():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.5.0c1"
    assert "wheel" in project["project"]["optional-dependencies"]["test"]
    assert __version__ == "0.5.0c1"


def test_built_wheel_contains_production_contracts(built_wheel):
    with zipfile.ZipFile(built_wheel) as bundle:
        names = set(bundle.namelist())
    assert "sedb_ral/schemas/production-operations-extension-plan.schema.json" in names
    assert "sedb_ral/schemas/production-operations-policy.schema.json" in names
    assert "sedb_ral/schemas/registry-extension-index.schema.json" in names
    assert built_wheel.name == "sedb_ral-0.5.0rc1-py3-none-any.whl"


def test_historical_r3b_a_acceptance_keeps_0_5_0a1():
    report = validate_phase3a_operations(ROOT)
    assert report.to_dict()["candidate_version"] == "0.5.0a1"
    assert report.passed is True
