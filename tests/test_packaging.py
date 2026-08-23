import json
import gzip
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from scripts.build_manifest import build_manifest, verify_manifest_at_commit
from scripts.build_reproducible import normalize_sdist

ROOT = Path(__file__).parents[1]


def build_clean_wheel(tmp_path: Path) -> Path:
    build_root = tmp_path / "build-source"
    build_root.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", build_root / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", build_root / "README.md")
    (build_root / "src").mkdir()
    shutil.copytree(
        ROOT / "src" / "sedb_ral",
        build_root / "src" / "sedb_ral",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    output = tmp_path / "wheel-output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--skip-dependency-check",
            "--outdir",
            str(output),
        ],
        cwd=build_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def checkpoint_tree_paths() -> set[str]:
    checkpoint = json.loads(
        (ROOT / "PHASE1A_CHECKPOINT.json").read_text(encoding="utf-8")
    )
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", checkpoint["checkpoint_commit"]],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    )
    return set(output.splitlines())


def test_public_contracts_exist_once():
    prefix = "src/sedb_ral/schemas/"
    schemas = sorted(
        path.removeprefix(prefix)
        for path in checkpoint_tree_paths()
        if path.startswith(prefix)
    )
    assert schemas == [
        "ctcl-receipt.schema.json",
        "identifier-discrimination.schema.json",
        "identifier-field.schema.json",
        "ledger-event.schema.json",
    ]
    assert not any(path.startswith("schemas/") for path in checkpoint_tree_paths())


def test_no_phase_1a_sqlite_or_send_adapter():
    paths = checkpoint_tree_paths()
    assert not any(path.endswith(".sqlite3") for path in paths)
    assert not any(path.startswith("src/sedb_ral/adapters/") for path in paths)


def test_manifest_matches_release_files():
    checkpoint = json.loads(
        (ROOT / "PHASE1A_CHECKPOINT.json").read_text(encoding="utf-8")
    )
    manifest = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert verify_manifest_at_commit(
        ROOT,
        manifest,
        checkpoint["checkpoint_commit"],
    ) == ()
    assert checkpoint["manifest_sha256"] == hashlib.sha256(
        manifest.encode("utf-8")
    ).hexdigest()


def test_manifest_changes_on_mutation_omission_and_extra(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    original = build_manifest(tmp_path, [first, second])
    first.write_text("changed", encoding="utf-8")
    assert build_manifest(tmp_path, [first, second]) != original
    assert build_manifest(tmp_path, [first]) != original
    third = tmp_path / "c.txt"
    third.write_text("c", encoding="utf-8")
    assert build_manifest(tmp_path, [first, second, third]) != original


def test_phase2_repository_gate_is_not_claimed_as_self_contained_in_wheel(
    tmp_path,
):
    wheel = build_clean_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())

    assert "sedb_ral/schemas/sedb-compatibility-receipt.schema.json" in members
    assert not any(name.startswith("profiles/") for name in members)
    assert not any(name.startswith("scripts/") for name in members)
    assert "VALIDATION_BASIC_PHASE2.json" not in members


def test_clean_installed_wheel_cli_reports_phase2_version(tmp_path):
    wheel = build_clean_wheel(tmp_path)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    venv = tmp_path / "clean-venv"
    create = subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert create.returncode == 0, create.stdout + create.stderr
    outside_checkout = tmp_path / "outside-checkout"
    outside_checkout.mkdir()
    python = venv / "Scripts" / "python.exe"
    install = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ],
        cwd=outside_checkout,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    cli = venv / "Scripts" / "sedb-ral.exe"

    result = subprocess.run(
        [str(cli), "--version"],
        cwd=outside_checkout,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "0.2.0"


def test_validation_record_has_retrievable_registered_anchor():
    value = json.loads(
        (ROOT / "VALIDATION_PHASE_1A.json").read_text(encoding="utf-8")
    )
    assert value["schema_version"] == "0.1"
    assert value["project"] == "SEDB-RAL"
    assert value["phase"] == "1A"
    assert value["validation"] == "passed"
    assert value["test_result"]["failed"] == 0
    assert value["test_result"]["passed"] > 0
    assert value["test_result"] == {
        "collected": 109,
        "passed": 108,
        "failed": 0,
        "skipped": 1,
        "final_run_status": "confirmed_after_corrected_artifact_closure",
    }
    assert value["build_result"]["source_date_epoch"] == 1787484453
    assert value["build_result"]["independent_build_pairs_match"] is True
    assert len(value["build_result"]["wheel_sha256"]) == 64
    assert len(value["build_result"]["sdist_sha256"]) == 64
    assert value["ctcl"]["registered"]["id"] == value["ctcl"][
        "retrieved"
    ]["id"]
    assert value["ctcl"]["call_kind"] == "registered_anchor"
    assert value["ctcl"]["signature_verification_status"] == "not_performed"


def test_readme_names_basic_phase2_commands_pins_and_boundaries():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in (
        "$env:PYTHONPATH = \"src\"",
        "python -m pytest -q",
        "python -m pytest tests/test_sedb_v04b_integration.py -q",
        "python scripts/validate_phase2.py --sedb-archive $sedbArchive",
        "sedb-ral phase2 verify . --sedb-archive $sedbArchive",
        "python scripts/build_reproducible.py",
        "python -m build --wheel --no-isolation",
        "python -m venv",
        "pip install --no-deps",
        "sedb-ral --version",
    ):
        assert command in text
    for pin in (
        "SEDB-v0.4B-local.zip",
        "8980052",
        "159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8",
        "sedb-local==0.4.0b1",
        "139b9952bb283b2e95f7690d76e3c5fbcdc680aa",
        "MANIFEST.sha256",
        "114 entries",
    ):
        assert pin in text
    for boundary in (
        "expected_by_mapping",
        "unmapped",
        "only `contradiction` fails",
        "Windows-only",
        "ENOTSUP",
        "repository/source-checkout gate",
        "not self-contained wheel/sdist resources",
        "No live SEDB checkout input or mutation",
        "No Phase 3",
        "No registrar or federation",
        "No transport send",
    ):
        assert boundary in text


def test_sdist_normalization_removes_archive_time_variance(tmp_path):
    def write_source(path: Path, timestamp: int) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo("package-0.1")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            root.mtime = timestamp
            archive.addfile(root)
            payload = b"content\n"
            member = tarfile.TarInfo("package-0.1/file.txt")
            member.size = len(payload)
            member.mode = 0o644
            member.mtime = timestamp
            archive.addfile(member, io.BytesIO(payload))
        with path.open("wb") as raw:
            with gzip.GzipFile(
                fileobj=raw,
                mode="wb",
                filename="",
                mtime=timestamp,
            ) as compressed:
                compressed.write(buffer.getvalue())

    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    write_source(first, 100)
    write_source(second, 200)
    normalized_first = tmp_path / "normalized-first.tar.gz"
    normalized_second = tmp_path / "normalized-second.tar.gz"
    normalize_sdist(first, normalized_first, source_date_epoch=300)
    normalize_sdist(second, normalized_second, source_date_epoch=300)
    assert normalized_first.read_bytes() == normalized_second.read_bytes()
