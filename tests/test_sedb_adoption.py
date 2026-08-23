import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

import sedb_ral.sedb_adoption as adoption
from sedb_ral.sedb_adoption import (
    extract_verified_sedb,
    inspect_sedb_archive,
)


ROOT = Path(__file__).parents[1]
ARCHIVE = Path(r"C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip")
PROFILE = json.loads(
    (ROOT / "profiles/sedb-v0.4b-adoption.json").read_text(encoding="utf-8")
)
WRONG_HASH = json.loads(
    (ROOT / "fixtures/sedb/wrong-archive-hash.json").read_text(encoding="utf-8")
)
PACKAGE_ROOT = "SEDB-v0.4B-local"


def archive_profile(archive: Path, **overrides: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "archive_filename": archive.name,
        "archive_size": archive.stat().st_size,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "package_name": "sedb-local",
        "package_version": "0.4.0b1",
        "source_commit": "139b9952bb283b2e95f7690d76e3c5fbcdc680aa",
        "manifest_path": "MANIFEST.sha256",
        "manifest_entry_count": 3,
    }
    profile.update(overrides)
    return profile


def package_members() -> dict[str, bytes]:
    return {
        "pyproject.toml": (
            b'[project]\nname = "sedb-local"\nversion = "0.4.0b1"\n'
        ),
        "SOURCE_COMMIT.txt": (
            b"source_commit: 139b9952bb283b2e95f7690d76e3c5fbcdc680aa\n"
        ),
        "data/payload.txt": b"immutable payload\n",
    }


def manifest_bytes(
    members: dict[str, bytes], *, corrupt_path: str | None = None
) -> bytes:
    lines = []
    for name, payload in members.items():
        digest = hashlib.sha256(payload).hexdigest()
        if name == corrupt_path:
            digest = "0" * 64
        lines.append(f"{digest}  {name}\n")
    return "".join(lines).encode("utf-8")


def write_package(
    archive: Path,
    *,
    members: dict[str, bytes] | None = None,
    corrupt_manifest_path: str | None = None,
) -> dict[str, bytes]:
    package = package_members() if members is None else members
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in package.items():
            bundle.writestr(f"{PACKAGE_ROOT}/{name}", payload)
        bundle.writestr(
            f"{PACKAGE_ROOT}/MANIFEST.sha256",
            manifest_bytes(package, corrupt_path=corrupt_manifest_path),
        )
    return package


def write_package_with_extra_info(archive: Path, info: zipfile.ZipInfo) -> None:
    members = package_members()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members.items():
            bundle.writestr(f"{PACKAGE_ROOT}/{name}", payload)
        bundle.writestr(
            f"{PACKAGE_ROOT}/MANIFEST.sha256", manifest_bytes(members)
        )
        bundle.writestr(info, b"unsafe")


def test_exact_archive_is_adoption_candidate():
    result = inspect_sedb_archive(ARCHIVE, PROFILE)

    assert result.compatible is True
    assert result.archive_sha256 == PROFILE["archive_sha256"].lower()
    assert result.package_version == "0.4.0b1"
    assert result.source_commit == "139b9952bb283b2e95f7690d76e3c5fbcdc680aa"
    assert result.manifest_entry_count == 114
    assert result.manifest_verified is True
    assert result.error_codes == ()


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("archive_filename", "SEDB-v0.4B-other.zip", "archive_filename_mismatch"),
        ("archive_size", 8980053, "archive_size_mismatch"),
        ("archive_sha256", "0" * 64, "archive_hash_mismatch"),
    ],
)
def test_each_outer_archive_pin_fails_before_zip_inspection(
    field, value, error_code, monkeypatch
):
    profile = dict(PROFILE)
    profile[field] = value

    def fail_if_opened(*args, **kwargs):
        raise AssertionError("untrusted ZIP was opened")

    monkeypatch.setattr(zipfile.ZipFile, "__init__", fail_if_opened)

    result = inspect_sedb_archive(ARCHIVE, profile)

    assert result.compatible is False
    assert result.error_codes == (error_code,)


def test_wrong_hash_fails_before_extraction(tmp_path):
    target = tmp_path / "extracted"

    result = inspect_sedb_archive(ARCHIVE, WRONG_HASH)

    assert result.error_codes == ("archive_hash_mismatch",)
    with pytest.raises(ValueError, match="archive_hash_mismatch"):
        extract_verified_sedb(ARCHIVE, WRONG_HASH, target)
    assert not target.exists()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape.py",
        "/absolute.py",
        r"C:\drive.py",
    ],
)
def test_unsafe_member_path_is_rejected_without_writing_outside(
    tmp_path, unsafe_name
):
    archive = tmp_path / "unsafe.zip"
    info = zipfile.ZipInfo(unsafe_name)
    write_package_with_extra_info(archive, info)

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.error_codes == ("archive_path_unsafe",)
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="archive_path_unsafe"):
        extract_verified_sedb(archive, archive_profile(archive), target)
    assert not target.exists()
    assert not (tmp_path.parent / "escape.py").exists()


def test_duplicate_member_name_is_rejected(tmp_path):
    archive = tmp_path / "duplicate.zip"
    members = package_members()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, payload in members.items():
                bundle.writestr(f"{PACKAGE_ROOT}/{name}", payload)
            bundle.writestr(
                f"{PACKAGE_ROOT}/MANIFEST.sha256", manifest_bytes(members)
            )
            bundle.writestr(f"{PACKAGE_ROOT}/data/payload.txt", b"duplicate")

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.error_codes == ("archive_path_unsafe",)


def test_symlink_member_is_rejected(tmp_path):
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    write_package_with_extra_info(archive, info)

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.error_codes == ("archive_path_unsafe",)


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("package_name", "sedb-other", "package_name_mismatch"),
        ("package_version", "0.4.0b2", "package_version_mismatch"),
        ("source_commit", "0" * 40, "source_commit_mismatch"),
        ("manifest_entry_count", 4, "manifest_entry_count_mismatch"),
    ],
)
def test_each_internal_identity_pin_has_an_executed_corruption(
    tmp_path, field, value, error_code
):
    archive = tmp_path / "package.zip"
    write_package(archive)
    profile = archive_profile(archive, **{field: value})

    result = inspect_sedb_archive(archive, profile)

    assert result.compatible is False
    assert result.error_codes == (error_code,)


def test_internal_manifest_mutation_is_detected(tmp_path):
    archive = tmp_path / "manifest-corrupt.zip"
    write_package(archive, corrupt_manifest_path="data/payload.txt")

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.manifest_verified is False
    assert result.error_codes == ("manifest_hash_mismatch",)


def test_one_byte_archive_mutation_turns_the_outer_hash_gate_red(tmp_path):
    archive = tmp_path / PROFILE["archive_filename"]
    mutated = bytearray(ARCHIVE.read_bytes())
    mutated[len(mutated) // 2] ^= 1
    archive.write_bytes(mutated)

    result = inspect_sedb_archive(archive, PROFILE)

    assert result.compatible is False
    assert result.error_codes == ("archive_hash_mismatch",)


def test_verified_archive_extracts_members_without_extractall(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    members = write_package(archive)
    target = tmp_path / "new-target"

    def forbidden_extractall(*args, **kwargs):
        raise AssertionError("extractall must never be called")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden_extractall)

    extracted = extract_verified_sedb(archive, archive_profile(archive), target)

    assert extracted == target
    assert target.is_dir()
    for name, payload in members.items():
        assert (target / PACKAGE_ROOT / name).read_bytes() == payload
    assert (target / PACKAGE_ROOT / "MANIFEST.sha256").is_file()


def test_archive_replacement_after_inspection_is_rejected(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    write_package(archive)
    profile = archive_profile(archive)
    target = tmp_path / "new-target"
    original_inspect = adoption.inspect_sedb_archive
    mutated = False

    def inspect_then_replace(archive_path, candidate_profile):
        nonlocal mutated
        result = original_inspect(archive_path, candidate_profile)
        if not mutated:
            replacement = package_members()
            replacement["data/payload.txt"] = b"replacement payload\n"
            write_package(Path(archive_path), members=replacement)
            mutated = True
        return result

    monkeypatch.setattr(adoption, "inspect_sedb_archive", inspect_then_replace)

    with pytest.raises(ValueError, match=r"archive_(size|hash)_mismatch"):
        adoption.extract_verified_sedb(archive, profile, target)

    assert not target.exists()


def test_extraction_requires_a_new_target_and_preserves_existing_content(tmp_path):
    archive = tmp_path / "package.zip"
    write_package(archive)
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        extract_verified_sedb(archive, archive_profile(archive), target)

    assert sentinel.read_text(encoding="utf-8") == "keep"
