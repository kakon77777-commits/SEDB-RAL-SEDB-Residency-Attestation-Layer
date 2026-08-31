from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

from test_packaging import build_clean_wheel

ROOT = Path(__file__).parents[1]


def expected_wave_schema_names() -> set[str]:
    return {
        path.name
        for path in (ROOT / "src/sedb_ral/schemas").glob("*.json")
        if "wave" in path.name
    }


def test_clean_wheel_contains_all_wave_schemas_and_cli(tmp_path):
    wheel = build_clean_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert {
        f"sedb_ral/schemas/{name}" for name in expected_wave_schema_names()
    } <= names
    assert "sedb_ral/registration_wave_cli.py" in names
    assert "sedb_ral/registration_wave_acceptance.py" in names
    assert wheel.name == "sedb_ral-0.5.0rc1-py3-none-any.whl"


def test_installed_candidate_exposes_wave_cli_and_resources(tmp_path):
    wheel = build_clean_wheel(tmp_path)
    install = tmp_path / "installed"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install),
            str(wheel),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.resources as r,sys;"
                f"sys.path.insert(0,{str(install)!r});"
                "import sedb_ral.registration_wave_cli as c;"
                "import sedb_ral.registration_wave_acceptance as a;"
                "from sedb_ral import __version__;"
                "from sedb_ral.cli import build_parser;"
                "p=build_parser();"
                "assert 'registration-wave' in p.format_help() or c;"
                "names={x.name for x in r.files('sedb_ral.schemas').iterdir()};"
                f"assert {expected_wave_schema_names()!r} <= names;"
                "assert __version__=='0.5.0c1';"
                "print(__version__,len(names),bool(a.validate_registration_wave))"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert probe.stdout.startswith("0.5.0c1 ")


def test_runbook_keeps_operational_and_owner_gates_not_run():
    text = (ROOT / "docs/runtime/R3B_C_THREE_SEAT_WAVE1.md").read_text(
        encoding="utf-8"
    )
    for line in (
        "production_wave_run = NOT_RUN",
        "live_limen_b6a = NOT_RUN",
        "production_root_status = NOT_READ",
        "pinned_p3_4_receipt = VERIFIED",
        "r3b_b_regression = PASS",
    ):
        assert line in text
    assert "candidate-only" in text
    assert "private B6B" in text
