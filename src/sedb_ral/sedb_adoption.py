from __future__ import annotations

import errno
import hashlib
import io
import os
import re
import shutil
import stat
import tempfile
import tomllib
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_MANIFEST_LINE = re.compile(r"^([0-9a-fA-F]{64})  (.+)$")
_SOURCE_COMMIT_LINE = re.compile(r"^source_commit:\s*([0-9a-fA-F]{40})\s*$")
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"aux", "clock$", "con", "conin$", "conout$", "nul", "prn"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_SNAPSHOT_CHUNK_SIZE = 1024 * 1024


class _ArchiveSizeMismatch(Exception):
    pass


@dataclass(frozen=True)
class SEDBAdoptionInspection:
    compatible: bool
    archive_sha256: str
    package_version: str | None
    source_commit: str | None
    manifest_entry_count: int
    manifest_verified: bool
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class _WindowsDirectoryHandle:
    path: Path
    value: int
    identity: tuple[int, int]


def _inspection_failure(
    archive_sha256: str,
    *error_codes: str,
    package_version: str | None = None,
    source_commit: str | None = None,
    manifest_entry_count: int = 0,
    manifest_verified: bool = False,
) -> SEDBAdoptionInspection:
    return SEDBAdoptionInspection(
        compatible=False,
        archive_sha256=archive_sha256,
        package_version=package_version,
        source_commit=source_commit,
        manifest_entry_count=manifest_entry_count,
        manifest_verified=manifest_verified,
        error_codes=tuple(error_codes),
    )


def _read_archive_snapshot(path: Path, expected_size: int) -> bytes:
    with path.open("rb") as source:
        if os.fstat(source.fileno()).st_size != expected_size:
            raise _ArchiveSizeMismatch

        chunks: list[bytes] = []
        remaining = expected_size + 1
        while remaining:
            read_size = min(_SNAPSHOT_CHUNK_SIZE, remaining)
            chunk = source.read(read_size)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if len(chunk) < read_size:
                break

    snapshot = b"".join(chunks)
    if len(snapshot) != expected_size:
        raise _ArchiveSizeMismatch
    return snapshot


def _expected_archive_size(profile: Mapping[str, object]) -> int | None:
    expected_size = profile.get("archive_size")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
    ):
        return None
    return expected_size


def _safe_member_parts(name: str) -> tuple[str, ...] | None:
    normalized = unicodedata.normalize("NFKC", name).replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return None

    without_directory_marker = (
        normalized[:-1] if normalized.endswith("/") else normalized
    )
    raw_parts = tuple(without_directory_marker.split("/"))
    if not raw_parts:
        return None

    parts: list[str] = []
    for raw_part in raw_parts:
        part = unicodedata.normalize("NFKC", raw_part)
        windows_stem = part.casefold().split(".", 1)[0]
        if (
            part in {"", ".", ".."}
            or "/" in part
            or "\\" in part
            or part.endswith((".", " "))
            or ":" in part
            or windows_stem in _WINDOWS_RESERVED_COMPONENTS
        ):
            return None
        parts.append(part)
    return tuple(parts)


def _validated_members(
    bundle: zipfile.ZipFile,
) -> tuple[dict[str, zipfile.ZipInfo], tuple[str, ...]]:
    members: dict[str, zipfile.ZipInfo] = {}
    canonical_keys: set[str] = set()
    for info in bundle.infolist():
        parts = _safe_member_parts(info.filename)
        unix_mode = info.external_attr >> 16
        if parts is None or stat.S_ISLNK(unix_mode):
            return {}, ("archive_path_unsafe",)

        canonical_name = "/".join(parts)
        canonical_key = "/".join(part.casefold() for part in parts)
        if canonical_key in canonical_keys:
            return {}, ("archive_path_unsafe",)
        canonical_keys.add(canonical_key)
        members[canonical_name] = info
    return members, ()


def _member_name(package_root: str, relative_name: str) -> str:
    return f"{package_root}/{relative_name}" if package_root else relative_name


def _required_member(
    members: Mapping[str, zipfile.ZipInfo], package_root: str, relative_name: str
) -> zipfile.ZipInfo | None:
    return members.get(_member_name(package_root, relative_name))


def _read_member(bundle: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    with bundle.open(info, "r") as source:
        return source.read()


def _parse_source_commit(payload: bytes) -> str | None:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None

    for line in lines:
        match = _SOURCE_COMMIT_LINE.fullmatch(line)
        if match:
            return match.group(1).lower()
    if len(lines) == 1 and re.fullmatch(r"[0-9a-fA-F]{40}", lines[0].strip()):
        return lines[0].strip().lower()
    return None


def _parse_manifest(payload: bytes) -> dict[str, str] | None:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None

    entries: dict[str, str] = {}
    canonical_keys: set[str] = set()
    for line in lines:
        if not line:
            continue
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None:
            return None
        digest, name = match.groups()
        parts = _safe_member_parts(name)
        if parts is None:
            return None
        canonical_name = "/".join(parts)
        canonical_key = "/".join(part.casefold() for part in parts)
        if canonical_key in canonical_keys:
            return None
        canonical_keys.add(canonical_key)
        entries[canonical_name] = digest.lower()
    return entries


def _inspect_zip(
    bundle: zipfile.ZipFile,
    profile: Mapping[str, object],
    archive_sha256: str,
) -> SEDBAdoptionInspection:
    members, member_errors = _validated_members(bundle)
    if member_errors:
        return _inspection_failure(archive_sha256, *member_errors)

    manifest_path = profile.get("manifest_path")
    if not isinstance(manifest_path, str):
        return _inspection_failure(archive_sha256, "archive_member_missing")

    manifest_matches = [
        name
        for name in members
        if name == manifest_path or name.endswith(f"/{manifest_path}")
    ]
    if len(manifest_matches) != 1:
        return _inspection_failure(archive_sha256, "archive_member_missing")

    manifest_name = manifest_matches[0]
    package_root = manifest_name[: -len(manifest_path)].removesuffix("/")
    pyproject_info = _required_member(members, package_root, "pyproject.toml")
    source_commit_info = _required_member(members, package_root, "SOURCE_COMMIT.txt")
    manifest_info = members[manifest_name]
    if pyproject_info is None or source_commit_info is None:
        return _inspection_failure(archive_sha256, "archive_member_missing")

    try:
        pyproject = tomllib.loads(_read_member(bundle, pyproject_info).decode("utf-8"))
        project = pyproject["project"]
        package_name = project["name"]
        package_version = project["version"]
    except (KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return _inspection_failure(archive_sha256, "archive_metadata_invalid")

    if not isinstance(package_name, str) or not isinstance(package_version, str):
        return _inspection_failure(archive_sha256, "archive_metadata_invalid")

    source_commit = _parse_source_commit(_read_member(bundle, source_commit_info))
    manifest = _parse_manifest(_read_member(bundle, manifest_info))
    if source_commit is None or manifest is None:
        return _inspection_failure(
            archive_sha256,
            "archive_metadata_invalid",
            package_version=package_version,
            source_commit=source_commit,
        )

    manifest_entry_count = len(manifest)
    errors: list[str] = []
    if package_name != profile.get("package_name"):
        errors.append("package_name_mismatch")
    if package_version != profile.get("package_version"):
        errors.append("package_version_mismatch")
    if source_commit != profile.get("source_commit"):
        errors.append("source_commit_mismatch")

    expected_count = profile.get("manifest_entry_count")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or manifest_entry_count != expected_count
    ):
        errors.append("manifest_entry_count_mismatch")

    archived_files = {
        name.removeprefix(f"{package_root}/") if package_root else name: info
        for name, info in members.items()
        if name != manifest_name and not info.is_dir()
    }
    manifest_verified = set(archived_files) == set(manifest)
    if manifest_verified:
        for name, expected_digest in manifest.items():
            actual_digest = hashlib.sha256(
                _read_member(bundle, archived_files[name])
            ).hexdigest()
            if actual_digest != expected_digest:
                manifest_verified = False
                break
    if not manifest_verified:
        errors.append("manifest_hash_mismatch")

    return SEDBAdoptionInspection(
        compatible=not errors,
        archive_sha256=archive_sha256,
        package_version=package_version,
        source_commit=source_commit,
        manifest_entry_count=manifest_entry_count,
        manifest_verified=manifest_verified and manifest_entry_count == expected_count,
        error_codes=tuple(errors),
    )


def _inspect_snapshot(
    archive_path: Path,
    profile: Mapping[str, object],
    snapshot: bytes,
) -> SEDBAdoptionInspection:
    archive_size = len(snapshot)
    archive_sha256 = hashlib.sha256(snapshot).hexdigest()
    if archive_path.name != profile.get("archive_filename"):
        return _inspection_failure(archive_sha256, "archive_filename_mismatch")

    expected_size = profile.get("archive_size")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or archive_size != expected_size
    ):
        return _inspection_failure(archive_sha256, "archive_size_mismatch")

    expected_hash = profile.get("archive_sha256")
    if not isinstance(expected_hash, str) or archive_sha256 != expected_hash.lower():
        return _inspection_failure(archive_sha256, "archive_hash_mismatch")

    try:
        with zipfile.ZipFile(io.BytesIO(snapshot), "r") as bundle:
            return _inspect_zip(bundle, profile, archive_sha256)
    except (OSError, zipfile.BadZipFile):
        return _inspection_failure(archive_sha256, "archive_invalid")


def inspect_sedb_archive(
    archive: str | Path, profile: Mapping[str, object]
) -> SEDBAdoptionInspection:
    archive_path = Path(archive)
    if archive_path.name != profile.get("archive_filename"):
        return _inspection_failure("", "archive_filename_mismatch")
    expected_size = _expected_archive_size(profile)
    if expected_size is None:
        return _inspection_failure("", "archive_size_mismatch")
    try:
        snapshot = _read_archive_snapshot(archive_path, expected_size)
    except _ArchiveSizeMismatch:
        return _inspection_failure("", "archive_size_mismatch")
    except OSError:
        return _inspection_failure("", "archive_unavailable")
    return _inspect_snapshot(archive_path, profile, snapshot)


def _open_windows_directory(path: Path, access: int) -> int:
    if os.name != "nt":
        raise OSError(
            errno.ENOTSUP,
            "operation-bound directory handles are supported only on Windows",
            path,
        )

    import ctypes
    from ctypes import wintypes

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        access,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _windows_handle_identity(handle: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class _FileTime(ctypes.Structure):
        _fields_ = [
            ("low", wintypes.DWORD),
            ("high", wintypes.DWORD),
        ]

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", _FileTime),
            ("last_access_time", _FileTime),
            ("last_write_time", _FileTime),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    get_information = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    file_index = (information.file_index_high << 32) | information.file_index_low
    return information.volume_serial_number, file_index


def _close_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _open_staging_handle(path: Path) -> _WindowsDirectoryHandle:
    handle = _open_windows_directory(path, 0x00010000)
    try:
        identity = _windows_handle_identity(handle)
    except BaseException:
        _close_windows_handle(handle)
        raise
    return _WindowsDirectoryHandle(path=path, value=handle, identity=identity)


def _directory_identity(path: Path) -> tuple[int, int]:
    if os.name == "nt":
        handle = _open_windows_directory(path, 0)
        try:
            return _windows_handle_identity(handle)
        finally:
            _close_windows_handle(handle)

    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("staging_identity_mismatch")
    return metadata.st_dev, metadata.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int]) -> None:
    if _directory_identity(path) != expected:
        raise RuntimeError("staging_identity_mismatch")


def _publish_staging_no_replace(
    staging: _WindowsDirectoryHandle, target: Path
) -> None:
    if os.name != "nt":
        raise OSError(
            errno.ENOTSUP,
            "operation-bound directory publish is supported only on Windows",
            target,
        )

    import ctypes
    from ctypes import wintypes

    class _FileRenameInformation(ctypes.Structure):
        _fields_ = [
            ("replace_if_exists", ctypes.c_ubyte),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        ]

    target_text = str(target)
    if target_text.startswith("\\\\"):
        nt_target = "\\??\\UNC\\" + target_text.lstrip("\\")
    else:
        nt_target = "\\??\\" + target_text
    encoded_target = nt_target.encode("utf-16-le")
    file_name_offset = _FileRenameInformation.file_name.offset
    buffer = ctypes.create_string_buffer(
        file_name_offset + len(encoded_target) + 2
    )
    information = _FileRenameInformation.from_buffer(buffer)
    information.replace_if_exists = 0
    information.root_directory = None
    information.file_name_length = len(encoded_target)
    ctypes.memmove(
        ctypes.addressof(buffer) + file_name_offset,
        encoded_target,
        len(encoded_target),
    )

    set_information = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    if not set_information(staging.value, 3, buffer, len(buffer)):
        error_number = ctypes.get_last_error()
        if error_number in {80, 183}:
            raise FileExistsError(
                errno.EEXIST,
                os.strerror(errno.EEXIST),
                target,
            )
        raise ctypes.WinError(error_number)


def extract_verified_sedb(
    archive: str | Path, profile: Mapping[str, object], target: str | Path
) -> Path:
    archive_path = Path(archive)
    target_path = Path(target)
    if archive_path.name != profile.get("archive_filename"):
        raise ValueError("sedb_archive_incompatible:archive_filename_mismatch")
    expected_size = _expected_archive_size(profile)
    if expected_size is None:
        raise ValueError("sedb_archive_incompatible:archive_size_mismatch")
    try:
        snapshot = _read_archive_snapshot(archive_path, expected_size)
    except _ArchiveSizeMismatch as error:
        raise ValueError(
            "sedb_archive_incompatible:archive_size_mismatch"
        ) from error
    except OSError as error:
        raise ValueError("sedb_archive_incompatible:archive_unavailable") from error
    inspection = _inspect_snapshot(archive_path, profile, snapshot)
    if not inspection.compatible:
        codes = ",".join(inspection.error_codes)
        raise ValueError(f"sedb_archive_incompatible:{codes}")

    with zipfile.ZipFile(io.BytesIO(snapshot), "r") as bundle:
        members, member_errors = _validated_members(bundle)
        if member_errors:
            raise ValueError(f"sedb_archive_incompatible:{member_errors[0]}")

        target_parent = target_path.parent.resolve(strict=True)
        publish_target = target_parent / target_path.name
        if os.path.lexists(publish_target):
            raise FileExistsError(publish_target)
        if os.name != "nt":
            raise OSError(
                errno.ENOTSUP,
                "operation-bound extraction publish is supported only on Windows",
                publish_target,
            )
        staging_path = Path(
            tempfile.mkdtemp(
                prefix=f".{target_path.name}.sedb-",
                dir=target_parent,
            )
        )
        staging_handle = _open_staging_handle(staging_path)
        try:
            for canonical_name, info in members.items():
                destination = staging_path.joinpath(*canonical_name.split("/"))
                resolved_destination = destination.resolve(strict=False)
                if not resolved_destination.is_relative_to(staging_path):
                    raise ValueError(
                        "sedb_archive_incompatible:archive_path_unsafe"
                    )
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info, "r") as member_source, destination.open(
                    "xb"
                ) as sink:
                    shutil.copyfileobj(member_source, sink)
            _assert_directory_identity(staging_path, staging_handle.identity)
            _publish_staging_no_replace(staging_handle, publish_target)
            _assert_directory_identity(publish_target, staging_handle.identity)
        finally:
            _close_windows_handle(staging_handle.value)

    return publish_target
