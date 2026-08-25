from __future__ import annotations

import json
from pathlib import Path

from sedb_ral.canonical import canonical_bytes
from sedb_ral.cli import main as cli_main
from sedb_ral.production_operations_contracts import default_dormant_policy
from sedb_ral.registry_root import registry_root_status
from production_operations_helpers import TIME_REF
from test_production_operations_layout import candidate_inputs, published_storage


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_bytes(canonical_bytes(value))


def test_status_cli_reports_absent_without_mutation(published_storage, capfd):
    code = cli_main(
        [
            "registry",
            "operations-extension-status",
            "--synthetic-storage-root",
            str(published_storage.parent.parent),
        ]
    )
    value = json.loads(capfd.readouterr().out)

    assert code == 0
    assert value["extensions_status"] == "absent"
    assert value["resident_count"] == 0


def test_prepare_cli_builds_verified_candidate_without_publication(
    published_storage, tmp_path, capfd
):
    plan, authority, acl, _policy = candidate_inputs(published_storage)
    candidate = published_storage.parent / plan["candidate_name"]
    candidate.mkdir()
    plan_path = tmp_path / "plan.json"
    authority_path = tmp_path / "authority.json"
    acl_path = tmp_path / "acl.json"
    write_json(plan_path, plan)
    write_json(authority_path, authority)
    write_json(acl_path, acl)

    code = cli_main(
        [
            "registry",
            "operations-extension-prepare",
            str(plan_path),
            str(authority_path),
            str(acl_path),
            "--synthetic-storage-root",
            str(published_storage.parent.parent),
        ]
    )
    value = json.loads(capfd.readouterr().out)

    assert code == 0
    assert value["verified"] is True
    assert (candidate / "extensions").is_dir()
    assert not (published_storage.final / "extensions").exists()
    assert plan["policy_digest"] == default_dormant_policy()["policy_digest"]


def test_plan_cli_reads_verified_status_and_binds_default_policy(
    published_storage, tmp_path, capfd
):
    acl = candidate_inputs(published_storage)[2]
    acl_path = tmp_path / "acl.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    write_json(acl_path, acl)
    write_json(checkpoint_path, {"checkpoint_digest": "sha256:sedb-ral-json-nfc-codepoint-v1:" + "3" * 64})

    code = cli_main(
        [
            "registry",
            "operations-extension-plan",
            "--candidate-id",
            "9b0c7d46-b94d-4b39-b59f-42f4d458955c",
            "--source-commit",
            "2470be770962556998925a739c3d1099dc830786",
            "--source-package-version",
            "0.5.0b1",
            "--filesystem",
            "NTFS",
            "--volume-identity",
            acl["volume_identity"],
            "--expected-owner-sid",
            acl["owner_sid"],
            "--acl-observation",
            str(acl_path),
            "--pre-checkpoint",
            str(checkpoint_path),
            "--time-ref",
            TIME_REF,
            "--synthetic-storage-root",
            str(published_storage.parent.parent),
        ]
    )
    value = json.loads(capfd.readouterr().out)

    assert code == 0
    assert value["policy_digest"] == default_dormant_policy()["policy_digest"]
    assert value["registry_id"] == registry_root_status(
        storage=published_storage
    )["registry_id"]
