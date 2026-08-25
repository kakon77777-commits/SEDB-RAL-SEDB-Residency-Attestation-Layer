from __future__ import annotations

import json
from pathlib import Path

from test_registry_root_contracts import (
    CANDIDATE_ID,
    FINAL_ROOT,
    OWNER_SID,
    PARENT_ROOT,
    TIME_REF,
    valid_acl,
    valid_authority,
    valid_plan,
)

from sedb_ral.canonical import canonical_bytes
from sedb_ral.cli import main
from sedb_ral.registry_root import RegistryStorage, prepare_registry_candidate
from sedb_ral.registry_root_contracts import plan_registry_root


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))
    return path


def cli_inputs(tmp_path: Path):
    plan = valid_plan()
    authority = valid_authority(plan)
    parent_acl = valid_acl(PARENT_ROOT)
    candidate_acl = valid_acl(plan["candidate_root"])
    inputs = tmp_path / "inputs"
    paths = {
        "plan": write_json(inputs / "plan.json", plan),
        "authority": write_json(inputs / "authority.json", authority),
        "parent_acl": write_json(inputs / "parent-acl.json", parent_acl),
        "candidate_acl": write_json(inputs / "candidate-acl.json", candidate_acl),
    }
    storage_root = tmp_path / "storage"
    storage = RegistryStorage.synthetic(storage_root)
    storage.parent.mkdir(parents=True)
    storage.candidate(plan).mkdir()
    return plan, authority, parent_acl, candidate_acl, paths, storage_root, storage


def common_args(paths, storage_root):
    return [
        str(paths["plan"]),
        str(paths["authority"]),
        str(paths["parent_acl"]),
        str(paths["candidate_acl"]),
        "--synthetic-storage-root",
        str(storage_root),
    ]


def test_root_plan_cli_matches_direct_core_bytes(capfd):
    expected = plan_registry_root(
        final_root=FINAL_ROOT,
        candidate_id=CANDIDATE_ID,
        source_commit="a" * 40,
        source_package_version="0.4.0",
        time_ref=TIME_REF,
        filesystem="NTFS",
        volume_identity="volume:test-d",
        expected_owner_sid=OWNER_SID,
    )

    code = main(
        [
            "registry",
            "root-plan",
            "--final-root",
            FINAL_ROOT,
            "--candidate-id",
            CANDIDATE_ID,
            "--source-commit",
            "a" * 40,
            "--source-package-version",
            "0.4.0",
            "--time-ref",
            TIME_REF,
            "--filesystem",
            "NTFS",
            "--volume-identity",
            "volume:test-d",
            "--expected-owner-sid",
            OWNER_SID,
        ]
    )

    assert code == 0
    assert canonical_bytes(json.loads(capfd.readouterr().out)) == canonical_bytes(
        expected
    )


def test_prepare_root_cli_matches_direct_core_bytes(tmp_path, capfd):
    direct = cli_inputs(tmp_path / "direct")
    expected = prepare_registry_candidate(
        direct[0], direct[1], direct[2], direct[3], storage=direct[6]
    )
    cli = cli_inputs(tmp_path / "cli")

    code = main(["registry", "prepare-root", *common_args(cli[4], cli[5])])

    assert code == 0
    assert canonical_bytes(json.loads(capfd.readouterr().out)) == canonical_bytes(
        expected
    )


def test_verify_publish_and_status_cli_round_trip(tmp_path, capfd):
    plan, _, _, _, paths, storage_root, storage = cli_inputs(tmp_path)
    common = common_args(paths, storage_root)
    assert main(["registry", "prepare-root", *common]) == 0
    capfd.readouterr()

    verification_path = tmp_path / "verification.json"
    assert (
        main(
            [
                "registry",
                "verify-root",
                *common,
                "--output",
                str(verification_path),
            ]
        )
        == 0
    )
    verification_stdout = json.loads(capfd.readouterr().out)
    assert verification_path.read_bytes() == canonical_bytes(verification_stdout)

    assert (
        main(
            [
                "registry",
                "publish-root",
                str(paths["plan"]),
                str(verification_path),
                "--synthetic-storage-root",
                str(storage_root),
            ]
        )
        == 0
    )
    publication = json.loads(capfd.readouterr().out)
    assert publication["published"] is True
    assert storage.final.is_dir()

    assert (
        main(
            [
                "registry",
                "root-status",
                "--expected-plan-digest",
                plan["plan_digest"],
                "--synthetic-storage-root",
                str(storage_root),
            ]
        )
        == 0
    )
    status = json.loads(capfd.readouterr().out)
    assert status["verified"] is True
    assert status["resident_count"] == 0


def test_registry_root_cli_error_is_typed_and_path_sanitized(tmp_path, capfd):
    _, _, _, _, paths, storage_root, storage = cli_inputs(tmp_path)
    storage.final.mkdir()
    secret_marker = storage.final / "do-not-leak.txt"
    secret_marker.write_bytes(b"preserve")

    code = main(["registry", "prepare-root", *common_args(paths, storage_root)])

    assert code == 2
    output = capfd.readouterr().out
    assert json.loads(output)["reason_codes"] == ["registry_root_exists"]
    assert str(storage_root) not in output
    assert "Traceback" not in output
    assert secret_marker.read_bytes() == b"preserve"


def test_registry_mutation_commands_require_all_authority_inputs(capfd):
    assert main(["registry", "prepare-root"]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == ["cli_usage_error"]
