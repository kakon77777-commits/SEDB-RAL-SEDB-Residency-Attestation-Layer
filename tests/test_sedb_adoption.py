import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

import pytest
from sedb_archive_locator import locate_sedb_v04b_archive, require_sedb_v04b_archive

import sedb_ral.sedb_adoption as adoption
from sedb_ral.sedb_adoption import (
    extract_verified_sedb,
    inspect_sedb_archive,
)

ROOT = Path(__file__).parents[1]
ARCHIVE = locate_sedb_v04b_archive(start=ROOT)
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
        "pyproject.toml": (b'[project]\nname = "sedb-local"\nversion = "0.4.0b1"\n'),
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
        bundle.writestr(f"{PACKAGE_ROOT}/MANIFEST.sha256", manifest_bytes(members))
        bundle.writestr(info, b"unsafe")


def test_exact_archive_is_adoption_candidate():
    result = inspect_sedb_archive(require_sedb_v04b_archive(ARCHIVE), PROFILE)

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

    result = inspect_sedb_archive(require_sedb_v04b_archive(ARCHIVE), profile)

    assert result.compatible is False
    assert result.error_codes == (error_code,)


def test_wrong_hash_fails_before_extraction(tmp_path):
    target = tmp_path / "extracted"

    archive = require_sedb_v04b_archive(ARCHIVE)
    result = inspect_sedb_archive(archive, WRONG_HASH)

    assert result.error_codes == ("archive_hash_mismatch",)
    with pytest.raises(ValueError, match="archive_hash_mismatch"):
        extract_verified_sedb(archive, WRONG_HASH, target)
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
def test_unsafe_member_path_is_rejected_without_writing_outside(tmp_path, unsafe_name):
    archive = tmp_path / "unsafe.zip"
    outside_path = tmp_path / "escape.py"
    info = zipfile.ZipInfo(unsafe_name)
    write_package_with_extra_info(archive, info)

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.error_codes == ("archive_path_unsafe",)
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="archive_path_unsafe"):
        extract_verified_sedb(archive, archive_profile(archive), target)
    assert not target.exists()
    assert not outside_path.exists()


def test_duplicate_member_name_is_rejected(tmp_path):
    archive = tmp_path / "duplicate.zip"
    members = package_members()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, payload in members.items():
                bundle.writestr(f"{PACKAGE_ROOT}/{name}", payload)
            bundle.writestr(f"{PACKAGE_ROOT}/MANIFEST.sha256", manifest_bytes(members))
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
    "unsafe_name",
    [
        f"{PACKAGE_ROOT}/data/trailing-dot.",
        f"{PACKAGE_ROOT}/data/trailing-space ",
        f"{PACKAGE_ROOT}/data/payload.txt:stream",
        f"{PACKAGE_ROOT}/data/CON.txt",
        f"{PACKAGE_ROOT}/data/COM\u00b9.txt",
    ],
    ids=[
        "trailing-dot",
        "trailing-space",
        "ntfs-ads",
        "reserved-device",
        "unicode-reserved-device",
    ],
)
def test_each_windows_hazardous_component_is_rejected(tmp_path, unsafe_name):
    archive = tmp_path / "windows-hazard.zip"
    write_package_with_extra_info(archive, zipfile.ZipInfo(unsafe_name))

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.error_codes == ("archive_path_unsafe",)
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="archive_path_unsafe"):
        extract_verified_sedb(archive, archive_profile(archive), target)
    assert not target.exists()


@pytest.mark.parametrize(
    ("first_name", "second_name"),
    [
        ("data/Case.txt", "data/case.txt"),
        ("data/caf\u00e9.txt", "data/cafe\u0301.txt"),
        ("data/A.txt", "data/\uff21.txt"),
        ("data/slash.txt", r"data\slash.txt"),
    ],
    ids=["casefold", "unicode-nfc", "unicode-nfkc", "slash-normalized"],
)
def test_windows_equivalent_member_names_are_rejected(
    tmp_path, first_name, second_name
):
    archive = tmp_path / "windows-collision.zip"
    members = package_members()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members.items():
            bundle.writestr(f"{PACKAGE_ROOT}/{name}", payload)
        bundle.writestr(f"{PACKAGE_ROOT}/MANIFEST.sha256", manifest_bytes(members))
        bundle.writestr(f"{PACKAGE_ROOT}/{first_name}", b"first")
        second_info = zipfile.ZipInfo("placeholder")
        second_info.filename = f"{PACKAGE_ROOT}/{second_name}"
        bundle.writestr(second_info, b"second")

    result = inspect_sedb_archive(archive, archive_profile(archive))

    assert result.error_codes == ("archive_path_unsafe",)
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="archive_path_unsafe"):
        extract_verified_sedb(archive, archive_profile(archive), target)
    assert not target.exists()


@pytest.mark.parametrize(
    "compatibility_separator",
    ["\uff3c", "\uff0f"],
    ids=["fullwidth-reverse-solidus", "fullwidth-solidus"],
)
def test_nfkc_compatibility_separator_collides_before_staging(
    tmp_path, compatibility_separator, monkeypatch
):
    archive = tmp_path / "separator-collision.zip"
    members = package_members()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members.items():
            bundle.writestr(f"{PACKAGE_ROOT}/{name}", payload)
        bundle.writestr(f"{PACKAGE_ROOT}/MANIFEST.sha256", manifest_bytes(members))
        bundle.writestr(f"{PACKAGE_ROOT}/data/a/b.txt", b"first")
        second_info = zipfile.ZipInfo("placeholder")
        second_info.filename = f"{PACKAGE_ROOT}/data/a{compatibility_separator}b.txt"
        bundle.writestr(second_info, b"second")

    def staging_must_not_be_created(*args, **kwargs):
        raise AssertionError("unsafe member reached staging creation")

    monkeypatch.setattr(tempfile, "mkdtemp", staging_must_not_be_created)
    profile = archive_profile(archive)

    result = inspect_sedb_archive(archive, profile)

    assert result.error_codes == ("archive_path_unsafe",)
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="archive_path_unsafe"):
        extract_verified_sedb(archive, profile, target)
    assert not target.exists()


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
    mutated = bytearray(require_sedb_v04b_archive(ARCHIVE).read_bytes())
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


def test_same_size_archive_replacement_cannot_change_extracted_bytes(
    tmp_path, monkeypatch
):
    archive = tmp_path / "package.zip"
    members = write_package(archive)
    profile = archive_profile(archive)
    target = tmp_path / "new-target"
    archive_size = archive.stat().st_size
    original_open = Path.open
    read_open_count = 0
    mutated = False

    class ReplaceAfterClose:
        def __init__(self, source):
            self.source = source

        def __getattr__(self, name):
            return getattr(self.source, name)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            nonlocal mutated
            self.source.close()
            if not mutated:
                with original_open(archive, "wb") as replacement:
                    replacement.write(b"\0" * archive_size)
                mutated = True

    def replace_after_verified_read(path, mode="r", *args, **kwargs):
        nonlocal read_open_count
        source = original_open(path, mode, *args, **kwargs)
        if Path(path) == archive and mode == "rb":
            read_open_count += 1
            return ReplaceAfterClose(source)
        return source

    monkeypatch.setattr(Path, "open", replace_after_verified_read)

    extracted = extract_verified_sedb(archive, profile, target)

    assert mutated is True
    assert read_open_count == 1
    assert archive.stat().st_size == archive_size
    assert archive.read_bytes() == b"\0" * archive_size
    assert (extracted / PACKAGE_ROOT / "data/payload.txt").read_bytes() == members[
        "data/payload.txt"
    ]


def test_archive_snapshot_reads_are_explicitly_bounded(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    write_package(archive)
    profile = archive_profile(archive)
    original_open = Path.open
    read_sizes: list[int] = []

    class BoundedReader:
        def __init__(self, source):
            self.source = source

        def __getattr__(self, name):
            return getattr(self.source, name)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.source.close()

        def read(self, size=-1):
            if size is None or size < 0:
                raise AssertionError("unbounded snapshot read")
            read_sizes.append(size)
            return self.source.read(size)

    def enforce_bounded_reads(path, mode="r", *args, **kwargs):
        source = original_open(path, mode, *args, **kwargs)
        if Path(path) == archive and mode == "rb":
            return BoundedReader(source)
        return source

    monkeypatch.setattr(Path, "open", enforce_bounded_reads)

    result = inspect_sedb_archive(archive, profile)

    assert result.compatible is True
    assert read_sizes
    assert max(read_sizes) <= profile["archive_size"] + 1


def test_oversized_archive_fails_fstat_before_read(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    write_package(archive)
    profile = archive_profile(archive)
    with archive.open("ab") as stream:
        stream.write(b"x")
    original_open = Path.open
    read_calls = 0

    class CountingReader:
        def __init__(self, source):
            self.source = source

        def __getattr__(self, name):
            return getattr(self.source, name)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.source.close()

        def read(self, size=-1):
            nonlocal read_calls
            read_calls += 1
            return self.source.read(size)

    def count_reads(path, mode="r", *args, **kwargs):
        source = original_open(path, mode, *args, **kwargs)
        if Path(path) == archive and mode == "rb":
            return CountingReader(source)
        return source

    monkeypatch.setattr(Path, "open", count_reads)

    result = inspect_sedb_archive(archive, profile)

    assert result.error_codes == ("archive_size_mismatch",)
    assert read_calls == 0


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


def test_copy_failure_never_deletes_a_swapped_staging_directory(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    write_package(archive)
    target = tmp_path / "published"
    original_open = Path.open
    swapped_root: Path | None = None
    replacement_sentinel: Path | None = None

    def swap_staging_then_fail(path, mode="r", *args, **kwargs):
        nonlocal swapped_root, replacement_sentinel
        candidate = Path(path)
        if mode == "xb" and swapped_root is None and candidate.is_relative_to(tmp_path):
            staging = next(
                parent for parent in candidate.parents if parent.parent == tmp_path
            )
            owned = staging.with_name(f"{staging.name}.owned")
            staging.rename(owned)
            staging.mkdir()
            replacement_sentinel = staging / "unrelated.txt"
            with original_open(replacement_sentinel, "w", encoding="utf-8") as stream:
                stream.write("do not delete")
            swapped_root = staging
            raise OSError("injected_copy_failure")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swap_staging_then_fail)

    with pytest.raises(
        (OSError, RuntimeError),
        match="injected_copy_failure|staging_identity_mismatch",
    ):
        extract_verified_sedb(archive, archive_profile(archive), target)

    assert swapped_root is not None
    assert swapped_root != target
    assert replacement_sentinel is not None
    assert replacement_sentinel.read_text(encoding="utf-8") == "do not delete"
    assert not target.exists()


def test_target_appearing_at_publish_is_preserved(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    write_package(archive)
    target = tmp_path / "published"
    sentinel = target / "unrelated.txt"
    original_publish = adoption._publish_staging_no_replace

    def target_appears_before_publish(source, destination):
        destination.mkdir()
        sentinel.write_text("do not replace", encoding="utf-8")
        return original_publish(source, destination)

    monkeypatch.setattr(
        adoption,
        "_publish_staging_no_replace",
        target_appears_before_publish,
    )

    with pytest.raises(FileExistsError):
        extract_verified_sedb(archive, archive_profile(archive), target)

    assert sentinel.read_text(encoding="utf-8") == "do not replace"


def test_cleanup_swap_after_identity_check_is_abandoned(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    write_package(archive)
    target = tmp_path / "published"
    original_open = Path.open
    original_rmtree = shutil.rmtree
    staging_path: Path | None = None
    cleanup_called = False

    def fail_first_member_copy(path, mode="r", *args, **kwargs):
        nonlocal staging_path
        candidate = Path(path)
        if mode == "xb" and staging_path is None:
            staging_path = next(
                parent for parent in candidate.parents if parent.parent == tmp_path
            )
            raise OSError("injected_copy_failure")
        return original_open(path, mode, *args, **kwargs)

    def swap_when_cleanup_starts(path, *args, **kwargs):
        nonlocal cleanup_called
        cleanup_called = True
        staging = Path(path)
        moved = staging.with_name(f"{staging.name}.owned")
        staging.rename(moved)
        staging.mkdir()
        (staging / "unrelated.txt").write_text("do not delete", encoding="utf-8")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_first_member_copy)
    monkeypatch.setattr(shutil, "rmtree", swap_when_cleanup_starts)

    with pytest.raises(OSError, match="injected_copy_failure"):
        extract_verified_sedb(archive, archive_profile(archive), target)

    assert cleanup_called is False
    assert staging_path is not None
    assert staging_path.is_dir()
    assert not target.exists()


def test_publish_uses_retained_directory_after_postcheck_swap(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    members = write_package(archive)
    target = tmp_path / "published"
    original_publish = adoption._publish_staging_no_replace
    swapped_path: Path | None = None
    replacement_sentinel: Path | None = None

    def swap_after_identity_check(source, destination):
        nonlocal swapped_path, replacement_sentinel
        staging = source.path if hasattr(source, "path") else source
        moved = staging.with_name(f"{staging.name}.owned")
        staging.rename(moved)
        staging.mkdir()
        replacement_sentinel = staging / "unrelated.txt"
        replacement_sentinel.write_text("replacement", encoding="utf-8")
        swapped_path = staging
        return original_publish(source, destination)

    monkeypatch.setattr(
        adoption,
        "_publish_staging_no_replace",
        swap_after_identity_check,
    )

    extracted = extract_verified_sedb(archive, archive_profile(archive), target)

    assert extracted == target
    assert (target / PACKAGE_ROOT / "data/payload.txt").read_bytes() == members[
        "data/payload.txt"
    ]
    assert not (target / "unrelated.txt").exists()
    assert swapped_path is not None
    assert replacement_sentinel is not None
    assert replacement_sentinel.read_text(encoding="utf-8") == "replacement"
