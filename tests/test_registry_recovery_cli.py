from __future__ import annotations

import json
from pathlib import Path

from test_registry_recovery import (
    CHECKPOINT_ID,
    RESTORE_ID,
    ROLLBACK_ID,
    published_storage,
)

from sedb_ral.canonical import canonical_bytes
from sedb_ral.cli import main
from sedb_ral.registry_recovery import verify_registry_checkpoint

ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"


def write_json(path: Path, value: object) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path


def test_checkpoint_restore_and_rollback_cli_round_trip(tmp_path, capfd):
    storage, _, authority = published_storage(tmp_path)
    authority_path = write_json(tmp_path / "authority.json", authority)
    storage_args = ["--synthetic-storage-root", str(tmp_path)]

    assert (
        main(
            [
                "registry",
                "checkpoint-root",
                "--root",
                ROOT,
                "--checkpoint-id",
                CHECKPOINT_ID,
                "--authority",
                str(authority_path),
                "--time-ref",
                "time:test:checkpoint",
                *storage_args,
            ]
        )
        == 0
    )
    checkpoint_result = json.loads(capfd.readouterr().out)
    checkpoint = Path(checkpoint_result["checkpoint_path"])
    assert verify_registry_checkpoint(checkpoint)["verified"] is True

    restore_output = tmp_path / "restore-result.json"
    assert (
        main(
            [
                "registry",
                "rehearse-restore",
                "--root",
                ROOT,
                "--checkpoint-root",
                str(checkpoint),
                "--rehearsal-id",
                RESTORE_ID,
                "--authority",
                str(authority_path),
                "--time-ref",
                "time:test:restore",
                "--output",
                str(restore_output),
                *storage_args,
            ]
        )
        == 0
    )
    restore_result = json.loads(capfd.readouterr().out)
    assert restore_result["restored"] is True
    assert restore_output.read_bytes() == canonical_bytes(restore_result)

    assert (
        main(
            [
                "registry",
                "rehearse-rollback",
                "--root",
                ROOT,
                "--checkpoint-root",
                str(checkpoint),
                "--rehearsal-id",
                ROLLBACK_ID,
                "--authority",
                str(authority_path),
                "--time-ref",
                "time:test:rollback",
                *storage_args,
            ]
        )
        == 0
    )
    rollback_result = json.loads(capfd.readouterr().out)
    assert rollback_result["passed"] is True
    assert rollback_result["red_control_error_code"] == (
        "checkpoint_manifest_digest_mismatch"
    )
    assert storage.final.is_dir()


def test_recovery_cli_rejects_escape_without_leaking_path(tmp_path, capfd):
    _, _, authority = published_storage(tmp_path)
    authority_path = write_json(tmp_path / "authority.json", authority)
    outside = tmp_path / "sensitive-outside"
    outside.mkdir()

    code = main(
        [
            "registry",
            "rehearse-restore",
            "--root",
            ROOT,
            "--checkpoint-root",
            str(outside),
            "--rehearsal-id",
            RESTORE_ID,
            "--authority",
            str(authority_path),
            "--time-ref",
            "time:test:restore",
            "--synthetic-storage-root",
            str(tmp_path),
        ]
    )

    assert code == 2
    output = capfd.readouterr().out
    assert json.loads(output)["reason_codes"] == ["checkpoint_path_escape"]
    assert str(outside) not in output
    assert "Traceback" not in output


def test_recovery_cli_requires_explicit_authority_and_time(capfd):
    assert main(["registry", "checkpoint-root"]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == ["cli_usage_error"]
