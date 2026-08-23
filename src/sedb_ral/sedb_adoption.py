from __future__ import annotations

import hashlib
import re
import shutil
import stat
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping


_MANIFEST_LINE = re.compile(r"^([0-9a-fA-F]{64})  (.+)$")
_SOURCE_COMMIT_LINE = re.compile(r"^source_commit:\s*([0-9a-fA-F]{40})\s*$")


@dataclass(frozen=True)
class SEDBAdoptionInspection:
    compatible: bool
    archive_sha256: str
    package_version: str | None
    source_commit: str | None
    manifest_entry_count: int
    manifest_verified: bool
    error_codes: tuple[str, ...]


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


def _sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    source.seek(0)
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _safe_member_parts(name: str) -> tuple[str, ...] | None:
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return None
    if re.match(r"^[A-Za-z]:", normalized):
        return None

    without_directory_marker = normalized[:-1] if normalized.endswith("/") else normalized
    parts = tuple(without_directory_marker.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    return parts


def _validated_members(
    bundle: zipfile.ZipFile,
) -> tuple[dict[str, zipfile.ZipInfo], tuple[str, ...]]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in bundle.infolist():
        parts = _safe_member_parts(info.filename)
        unix_mode = info.external_attr >> 16
        if parts is None or stat.S_ISLNK(unix_mode):
            return {}, ("archive_path_unsafe",)

        canonical_name = "/".join(parts)
        if canonical_name in members:
            return {}, ("archive_path_unsafe",)
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
        if canonical_name in entries:
            return None
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


def _inspect_open_archive(
    archive_path: Path,
    profile: Mapping[str, object],
    source: BinaryIO,
) -> SEDBAdoptionInspection:
    source.seek(0, 2)
    archive_size = source.tell()
    archive_sha256 = _sha256_stream(source)
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
        source.seek(0)
        with zipfile.ZipFile(source, "r") as bundle:
            return _inspect_zip(bundle, profile, archive_sha256)
    except (OSError, zipfile.BadZipFile):
        return _inspection_failure(archive_sha256, "archive_invalid")


def inspect_sedb_archive(
    archive: str | Path, profile: Mapping[str, object]
) -> SEDBAdoptionInspection:
    archive_path = Path(archive)
    try:
        with archive_path.open("rb") as source:
            return _inspect_open_archive(archive_path, profile, source)
    except OSError:
        return _inspection_failure("", "archive_unavailable")


def extract_verified_sedb(
    archive: str | Path, profile: Mapping[str, object], target: str | Path
) -> Path:
    archive_path = Path(archive)
    target_path = Path(target)
    inspection = inspect_sedb_archive(archive_path, profile)
    if not inspection.compatible:
        codes = ",".join(inspection.error_codes)
        raise ValueError(f"sedb_archive_incompatible:{codes}")
    if target_path.exists():
        raise FileExistsError(target_path)

    with archive_path.open("rb") as source:
        current_inspection = _inspect_open_archive(archive_path, profile, source)
        if not current_inspection.compatible:
            codes = ",".join(current_inspection.error_codes)
            raise ValueError(f"sedb_archive_incompatible:{codes}")

        source.seek(0)
        with zipfile.ZipFile(source, "r") as bundle:
            members, member_errors = _validated_members(bundle)
            if member_errors:
                raise ValueError(f"sedb_archive_incompatible:{member_errors[0]}")

            target_path.mkdir()
            target_root = target_path.resolve()
            try:
                for canonical_name, info in members.items():
                    destination = target_path.joinpath(*canonical_name.split("/"))
                    resolved_destination = destination.resolve(strict=False)
                    if not resolved_destination.is_relative_to(target_root):
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
            except BaseException:
                shutil.rmtree(target_path)
                raise

    return target_path
