import json
import gzip
import hashlib
import io
import tarfile
from pathlib import Path

from scripts.build_manifest import build_manifest, verify_manifest_at_commit
from scripts.build_reproducible import normalize_sdist

ROOT = Path(__file__).parents[1]


def test_public_contracts_exist_once():
    schema_root = ROOT / "src/sedb_ral/schemas"
    schemas = sorted(path.name for path in schema_root.glob("*.json"))
    assert schemas == [
        "ctcl-receipt.schema.json",
        "identifier-discrimination.schema.json",
        "identifier-field.schema.json",
        "ledger-event.schema.json",
    ]
    assert not (ROOT / "schemas").exists()


def test_no_phase_1a_sqlite_or_send_adapter():
    assert not list(ROOT.rglob("*.sqlite3"))
    assert not (ROOT / "src/sedb_ral/adapters").exists()


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


def test_readme_names_commands_and_phase_boundaries():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in (
        "sedb-ral canonicalize",
        "sedb-ral contract validate",
        "sedb-ral identifier check",
        "sedb-ral ledger verify",
        "sedb-ral phase1a verify",
    ):
        assert command in text
    for boundary in (
        "No SQLite projection",
        "No transport send",
        "No registrar",
        "No full incident corpus",
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
