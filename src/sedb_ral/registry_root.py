from __future__ import annotations

import ctypes
import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .registry_root_contracts import (
    PRODUCTION_REGISTRY_PARENT,
    PRODUCTION_REGISTRY_ROOT,
    ProductionRegistryManifest,
    RegistryHeadReceipt,
    RegistryRootPlan,
    bind_document_digest,
    verify_registry_acl,
    verify_root_authority,
)

HEAD_ZERO_REF = "control/heads/00000000000000000000.json"
EXPECTED_DIRECTORIES = frozenset(
    {
        "ledger",
        "ledger/events",
        "ledger/anchors",
        "control",
        "control/heads",
        "checkpoints",
        "rehearsals",
        "evidence",
    }
)
EXPECTED_FILES = frozenset(
    {
        "registry-manifest.json",
        HEAD_ZERO_REF,
        "evidence/initialization-receipt.json",
        "evidence/acl-receipt.json",
    }
)
RECOVERY_EVIDENCE_FILES = frozenset(
    {
        "evidence/checkpoint-receipt.json",
        "evidence/restore-rehearsal-receipt.json",
        "evidence/rollback-rehearsal-receipt.json",
    }
)


@dataclass(frozen=True)
class RegistryStorage:
    parent: Path
    final: Path
    synthetic_mode: bool = False

    @classmethod
    def production(cls) -> RegistryStorage:
        if os.name != "nt":
            raise RALValidationError(
                "platform_unsupported", "production registry requires Windows"
            )
        return cls(
            parent=Path(PRODUCTION_REGISTRY_PARENT),
            final=Path(PRODUCTION_REGISTRY_ROOT),
        )

    @classmethod
    def synthetic(cls, root: Path) -> RegistryStorage:
        physical_parent = Path(root) / "REGISTRY"
        return cls(
            parent=physical_parent,
            final=physical_parent / "SEDB-RAL",
            synthetic_mode=True,
        )

    def candidate(self, plan: Mapping[str, object]) -> Path:
        parsed = RegistryRootPlan.from_dict(plan).to_dict()
        return self.parent / str(parsed["candidate_name"])


def _storage(value: RegistryStorage | None) -> RegistryStorage:
    return value if value is not None else RegistryStorage.production()


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError as error:
        raise RALValidationError(
            "registry_path_unreadable", "registry path cannot be inspected"
        ) from error
    attributes = getattr(stat, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & 0x400)


def _windows_hardlink_names(path: Path) -> tuple[str, ...]:
    if os.name != "nt":
        return (str(path.resolve()),)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstFileNameW
    find_first.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
    ]
    find_first.restype = ctypes.c_void_p
    find_next = kernel32.FindNextFileNameW
    find_next.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
    ]
    find_next.restype = ctypes.c_int
    close = kernel32.FindClose
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    capacity = 32768
    length = ctypes.c_uint32(capacity)
    buffer = ctypes.create_unicode_buffer(capacity)
    handle = find_first(str(path.resolve()), 0, ctypes.byref(length), buffer)
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        raise RALValidationError(
            "registry_path_unreadable",
            f"hard-link names cannot be inspected ({error})",
        )
    names = [buffer.value]
    try:
        while True:
            length = ctypes.c_uint32(capacity)
            buffer = ctypes.create_unicode_buffer(capacity)
            if find_next(handle, ctypes.byref(length), buffer):
                names.append(buffer.value)
                continue
            error = ctypes.get_last_error()
            if error == 38:  # ERROR_HANDLE_EOF
                break
            raise RALValidationError(
                "registry_path_unreadable",
                f"hard-link names cannot be inspected ({error})",
            )
    finally:
        close(handle)
    return tuple(names)


def _has_multiple_hardlinks(path: Path) -> bool:
    if path.stat().st_nlink <= 1:
        return False
    if os.name != "nt":
        return True
    stable: set[str] | None = None
    for attempt in range(20):
        observed = {name.casefold() for name in _windows_hardlink_names(path)}
        if len(observed) <= 1:
            return False
        if stable is None:
            stable = observed
        elif observed != stable:
            return False
        if attempt < 19:
            time.sleep(0.05)
    return True


def _walk(
    root: Path,
    *,
    hardlink_exempt_prefixes: tuple[str, ...] = (),
) -> tuple[list[Path], list[Path]]:
    directories: list[Path] = []
    files: list[Path] = []
    for current, names, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        if _is_reparse(current_path):
            raise RALValidationError(
                "registry_root_reparse_point", "registry tree contains a reparse point"
            )
        folded = [name.casefold() for name in names + filenames]
        if len(folded) != len(set(folded)):
            raise RALValidationError(
                "registry_casefold_collision", "registry names collide by case"
            )
        for name in names:
            path = current_path / name
            if _is_reparse(path):
                raise RALValidationError(
                    "registry_root_reparse_point",
                    "registry tree contains a reparse point",
                )
            directories.append(path)
        for name in filenames:
            path = current_path / name
            if _is_reparse(path):
                raise RALValidationError(
                    "registry_root_reparse_point",
                    "registry tree contains a reparse point",
                )
            relative = path.relative_to(root).as_posix()
            hardlink_exempt = any(
                relative.startswith(prefix) for prefix in hardlink_exempt_prefixes
            )
            if not hardlink_exempt and _has_multiple_hardlinks(path):
                raise RALValidationError(
                    "registry_hard_link_detected",
                    "registry files must be copied values",
                )
            files.append(path)
    return directories, files


def _windows_stream_names(path: Path) -> tuple[str, ...]:
    if os.name != "nt":
        return ()

    class WIN32_FIND_STREAM_DATA(ctypes.Structure):
        _fields_ = [
            ("StreamSize", ctypes.c_longlong),
            ("cStreamName", ctypes.c_wchar * 296),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstStreamW
    find_first.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.POINTER(WIN32_FIND_STREAM_DATA),
        ctypes.c_uint32,
    ]
    find_first.restype = ctypes.c_void_p
    find_next = kernel32.FindNextStreamW
    find_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(WIN32_FIND_STREAM_DATA)]
    find_next.restype = ctypes.c_int
    find_close = kernel32.FindClose
    find_close.argtypes = [ctypes.c_void_p]
    find_close.restype = ctypes.c_int

    data = WIN32_FIND_STREAM_DATA()
    handle = find_first(str(path), 0, ctypes.byref(data), 0)
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        if error in {1, 38}:  # unsupported filesystem or no streams
            return ()
        raise RALValidationError(
            "registry_stream_inspection_failed", "alternate streams cannot be inspected"
        )
    streams: list[str] = []
    try:
        streams.append(data.cStreamName)
        while find_next(handle, ctypes.byref(data)):
            streams.append(data.cStreamName)
        error = ctypes.get_last_error()
        if error not in {0, 38}:
            raise RALValidationError(
                "registry_stream_inspection_failed",
                "alternate stream enumeration failed",
            )
    finally:
        find_close(handle)
    return tuple(streams)


def _reject_alternate_streams(files: list[Path]) -> None:
    for path in files:
        streams = _windows_stream_names(path)
        if any(name != "::$DATA" for name in streams):
            raise RALValidationError(
                "alternate_data_stream_detected",
                "registry file contains an alternate data stream",
            )


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        raise RALValidationError(
            "registry_path_escape", "registry path escaped its root"
        ) from error


def _reject_private_markers(root: Path, files: list[Path]) -> None:
    marker = "ai_home"
    for path in files:
        relative = _relative(path, root)
        if marker in relative.casefold():
            raise RALValidationError(
                "private_marker_detected", "private Residence marker detected"
            )
        data = path.read_bytes()
        lowered = data.lower()
        if b"\\ai_residence\\ai_home" in lowered or b"/ai_residence/ai_home" in lowered:
            raise RALValidationError(
                "private_marker_detected", "private Residence marker detected"
            )


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_material(
    root: Path, *, hardlink_exempt_prefixes: tuple[str, ...] = ()
) -> dict[str, object]:
    directories, files = _walk(
        root, hardlink_exempt_prefixes=hardlink_exempt_prefixes
    )
    _reject_alternate_streams(files)
    return {
        "directories": sorted(_relative(path, root) for path in directories),
        "files": {
            _relative(path, root): _raw_sha256(path)
            for path in sorted(files, key=lambda item: _relative(item, root))
        },
    }


def _tree_digest(
    root: Path, *, hardlink_exempt_prefixes: tuple[str, ...] = ()
) -> str:
    return sha256_ref(
        _tree_material(root, hardlink_exempt_prefixes=hardlink_exempt_prefixes)
    )


def registry_source_material(root: Path) -> dict[str, object]:
    return {
        "directories": sorted(EXPECTED_DIRECTORIES),
        "files": {
            relative: _raw_sha256(root / relative)
            for relative in sorted(EXPECTED_FILES)
        },
    }


def registry_source_digest(root: Path) -> str:
    return sha256_ref(registry_source_material(root))


def _write_new_json(path: Path, value: Mapping[str, object]) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(canonical_bytes(dict(value)))
    except FileExistsError as error:
        raise RALValidationError(
            "registry_candidate_not_empty", "candidate output already exists"
        ) from error
    except OSError as error:
        raise RALValidationError(
            "registry_candidate_unwritable", "candidate output cannot be written"
        ) from error


def _read_object(path: Path, invalid_code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(
            invalid_code, "registry JSON cannot be read"
        ) from error
    if not isinstance(value, dict):
        raise RALValidationError(invalid_code, "registry JSON must be an object")
    return value


def _verify_bound_receipt(value: Mapping[str, object], field: str, code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(code, "registry receipt digest differs")


def _verify_exact_tree(
    root: Path,
    *,
    allow_recovery_material: bool = False,
    allow_extensions: bool = False,
) -> dict[str, object]:
    recovery_hardlink_exemptions = (
        (
            "checkpoints/",
            "rehearsals/",
            "evidence/checkpoints/",
            "evidence/restores/",
            "evidence/rollbacks/",
        )
        if allow_recovery_material
        else ()
    )
    directories, files = _walk(
        root, hardlink_exempt_prefixes=recovery_hardlink_exemptions
    )
    _reject_alternate_streams(files)
    _reject_private_markers(root, files)
    relative_directories = {_relative(path, root) for path in directories}
    relative_files = {_relative(path, root) for path in files}
    event_files = [name for name in relative_files if name.startswith("ledger/events/")]
    anchor_files = [
        name for name in relative_files if name.startswith("ledger/anchors/")
    ]
    if event_files or anchor_files:
        raise RALValidationError(
            "nonempty_ledger", "empty registry ledger contains files"
        )
    directories_valid = relative_directories == EXPECTED_DIRECTORIES
    files_valid = relative_files == EXPECTED_FILES
    if allow_recovery_material:
        extra_directories = relative_directories - EXPECTED_DIRECTORIES
        extra_files = relative_files - EXPECTED_FILES
        directories_valid = EXPECTED_DIRECTORIES <= relative_directories and all(
            name.startswith(("checkpoints/", "rehearsals/"))
            or (
                allow_extensions
                and (name == "extensions" or name.startswith("extensions/"))
            )
            or name in {
                "evidence/checkpoints",
                "evidence/restores",
                "evidence/rollbacks",
            }
            for name in extra_directories
        )
        files_valid = EXPECTED_FILES <= relative_files and all(
            name.startswith(("checkpoints/", "rehearsals/"))
            or name in RECOVERY_EVIDENCE_FILES
            or (allow_extensions and name.startswith("extensions/"))
            or (
                allow_extensions
                and name.startswith("evidence/operations-extension-activation-")
                and name.endswith(".json")
            )
            or (
                name.startswith(
                    (
                        "evidence/checkpoints/checkpoint-",
                        "evidence/restores/restore-",
                        "evidence/rollbacks/rollback-",
                    )
                )
                and name.endswith(".json")
            )
            for name in extra_files
        )
    if not directories_valid or not files_valid:
        raise RALValidationError(
            "registry_layout_mismatch",
            "registry layout contains missing or unexpected paths",
        )

    manifest_value = _read_object(
        root / "registry-manifest.json", "registry_manifest_invalid_json"
    )
    manifest = ProductionRegistryManifest.from_dict(manifest_value).to_dict()
    try:
        head_value = _read_object(root / HEAD_ZERO_REF, "external_head_mismatch")
        head = RegistryHeadReceipt.from_dict(head_value).to_dict()
    except (RALValidationError, KeyError, TypeError) as error:
        raise RALValidationError(
            "external_head_mismatch", "head-zero receipt is invalid"
        ) from error
    if (
        head["manifest_digest"] != manifest["manifest_digest"]
        or head["registry_id"] != manifest["registry_id"]
    ):
        raise RALValidationError(
            "external_head_mismatch", "head-zero does not bind the manifest"
        )

    initialization = _read_object(
        root / "evidence/initialization-receipt.json",
        "initialization_receipt_invalid",
    )
    acl_receipt = _read_object(
        root / "evidence/acl-receipt.json", "acl_receipt_invalid"
    )
    _verify_bound_receipt(
        initialization, "receipt_digest", "initialization_receipt_digest_mismatch"
    )
    _verify_bound_receipt(acl_receipt, "receipt_digest", "acl_receipt_digest_mismatch")
    if initialization.get("manifest_digest") != manifest["manifest_digest"]:
        raise RALValidationError(
            "initialization_receipt_mismatch",
            "initialization receipt binds another manifest",
        )
    return {
        "registry_id": manifest["registry_id"],
        "manifest_digest": manifest["manifest_digest"],
        "control_digest": head["control_digest"],
        "plan_digest": initialization.get("operation_plan_digest"),
        "authority_digest": initialization.get("authority_digest"),
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
        "candidate_tree_digest": _tree_digest(
            root, hardlink_exempt_prefixes=recovery_hardlink_exemptions
        ),
        "source_tree_digest": registry_source_digest(root),
    }


def prepare_registry_candidate(
    plan: Mapping[str, object],
    authority: Mapping[str, object],
    parent_acl: Mapping[str, object],
    candidate_acl: Mapping[str, object],
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    parsed_plan = RegistryRootPlan.from_dict(plan).to_dict()
    verify_root_authority(
        authority=authority,
        plan_digest=parsed_plan["plan_digest"],
        exact_root=parsed_plan["final_root"],
    )
    selected = _storage(storage)
    candidate = selected.candidate(parsed_plan)
    if selected.final.exists():
        raise RALValidationError(
            "registry_root_exists", "the final registry root already exists"
        )
    if not selected.parent.is_dir() or _is_reparse(selected.parent):
        raise RALValidationError(
            "registry_parent_invalid", "the protected registry parent is unavailable"
        )
    if not candidate.is_dir() or _is_reparse(candidate):
        raise RALValidationError(
            "registry_candidate_invalid", "the protected candidate is unavailable"
        )
    owner_sid = str(parsed_plan["expected_owner_sid"])
    verify_registry_acl(
        observation=parent_acl,
        expected_root=PRODUCTION_REGISTRY_PARENT,
        expected_owner_sid=owner_sid,
    )
    if candidate_acl.get("owner_sid") != owner_sid:
        raise RALValidationError(
            "registry_acl_owner_mismatch", "parent and candidate owners differ"
        )
    verify_registry_acl(
        observation=candidate_acl,
        expected_root=str(parsed_plan["candidate_root"]),
        expected_owner_sid=owner_sid,
    )
    if (
        parent_acl.get("volume_identity") != parsed_plan["volume_identity"]
        or candidate_acl.get("volume_identity") != parsed_plan["volume_identity"]
    ):
        raise RALValidationError(
            "volume_identity_mismatch", "ACL observations bind another volume"
        )
    if any(candidate.iterdir()):
        raise RALValidationError(
            "registry_candidate_not_empty", "candidate must be empty"
        )

    for relative in sorted(
        EXPECTED_DIRECTORIES, key=lambda value: (value.count("/"), value)
    ):
        (candidate / relative).mkdir()

    registry_id = f"registry:{parsed_plan['candidate_id']}"
    manifest = bind_document_digest(
        {
            "schema": "sedb-ral.production-registry-manifest/0.1",
            "registry_id": registry_id,
            "root_kind": "public_registry",
            "canonical_ledger_ref": "ledger",
            "control_heads_ref": "control/heads",
            "checkpoints_ref": "checkpoints",
            "rehearsals_ref": "rehearsals",
            "evidence_ref": "evidence",
            "source_package_name": "sedb-ral",
            "source_package_version": parsed_plan["source_package_version"],
            "source_commit": parsed_plan["source_commit"],
            "canonicalization_version": parsed_plan["canonicalization_version"],
            "chain_version": parsed_plan["chain_version"],
            "filesystem": parsed_plan["filesystem"],
            "volume_identity": parsed_plan["volume_identity"],
            "acl_fingerprint": candidate_acl["acl_fingerprint"],
            "initialized_time_ref": parsed_plan["time_ref"],
            "initial_control_ref": HEAD_ZERO_REF,
            "not_claimed": [
                "resident_registration",
                "private_access",
                "offsite_backup",
            ],
        },
        "manifest_digest",
    )
    ProductionRegistryManifest.from_dict(manifest)
    head = bind_document_digest(
        {
            "schema": "sedb-ral.registry-head-receipt/0.1",
            "registry_id": registry_id,
            "control_sequence": 0,
            "ledger_event_count": 0,
            "ledger_head": None,
            "last_event_id": None,
            "manifest_digest": manifest["manifest_digest"],
            "previous_control_digest": None,
            "recorded_time_ref": parsed_plan["time_ref"],
            "not_claimed": [
                "resident_registration",
                "external_backup",
                "nonempty_ledger",
            ],
        },
        "control_digest",
    )
    RegistryHeadReceipt.from_dict(head)
    acl_receipt = bind_document_digest(
        {
            "schema": "sedb-ral.registry-acl-receipt/0.1",
            "registry_id": registry_id,
            "parent_acl_fingerprint": parent_acl["acl_fingerprint"],
            "candidate_acl_fingerprint": candidate_acl["acl_fingerprint"],
            "required_full_control_sids": candidate_acl["required_full_control_sids"],
            "broad_write_count": 0,
            "observed_time_ref": candidate_acl["observed_time_ref"],
            "not_claimed": [
                "offsite_backup",
                "private_confidentiality",
                "multi_host_security",
            ],
        },
        "receipt_digest",
    )
    initialization = bind_document_digest(
        {
            "schema": "sedb-ral.registry-initialization-receipt/0.1",
            "registry_id": registry_id,
            "operation_plan_digest": parsed_plan["plan_digest"],
            "authority_digest": authority["authority_digest"],
            "manifest_digest": manifest["manifest_digest"],
            "initial_control_digest": head["control_digest"],
            "parent_acl_fingerprint": parent_acl["acl_fingerprint"],
            "candidate_acl_fingerprint": candidate_acl["acl_fingerprint"],
            "ledger_event_count": 0,
            "resident_event_count": 0,
            "private_read_count": 0,
            "network_effect_count": 0,
            "external_effect_count": 0,
            "initialized_time_ref": parsed_plan["time_ref"],
            "not_claimed": [
                "resident_registration",
                "private_access",
                "offsite_backup",
            ],
        },
        "receipt_digest",
    )
    _write_new_json(candidate / "registry-manifest.json", manifest)
    _write_new_json(candidate / HEAD_ZERO_REF, head)
    _write_new_json(candidate / "evidence/acl-receipt.json", acl_receipt)
    _write_new_json(candidate / "evidence/initialization-receipt.json", initialization)
    verification = verify_registry_candidate(
        parsed_plan,
        authority,
        parent_acl,
        candidate_acl,
        storage=selected,
    )
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-initialization-result/0.1",
            "prepared": True,
            "registry_id": registry_id,
            "operation_plan_digest": parsed_plan["plan_digest"],
            "candidate_tree_digest": verification["candidate_tree_digest"],
            "manifest_digest": manifest["manifest_digest"],
            "control_digest": head["control_digest"],
            "ledger_event_count": 0,
            "resident_event_count": 0,
            "private_read_count": 0,
            "network_effect_count": 0,
            "external_effect_count": 0,
        },
        "result_digest",
    )


def verify_registry_candidate(
    plan: Mapping[str, object],
    authority: Mapping[str, object],
    parent_acl: Mapping[str, object],
    candidate_acl: Mapping[str, object],
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    parsed_plan = RegistryRootPlan.from_dict(plan).to_dict()
    verify_root_authority(
        authority=authority,
        plan_digest=parsed_plan["plan_digest"],
        exact_root=parsed_plan["final_root"],
    )
    selected = _storage(storage)
    if selected.final.exists():
        raise RALValidationError(
            "registry_root_exists", "the final registry root already exists"
        )
    owner_sid = str(parsed_plan["expected_owner_sid"])
    verify_registry_acl(
        observation=parent_acl,
        expected_root=PRODUCTION_REGISTRY_PARENT,
        expected_owner_sid=owner_sid,
    )
    verify_registry_acl(
        observation=candidate_acl,
        expected_root=str(parsed_plan["candidate_root"]),
        expected_owner_sid=owner_sid,
    )
    if (
        parent_acl.get("volume_identity") != parsed_plan["volume_identity"]
        or candidate_acl.get("volume_identity") != parsed_plan["volume_identity"]
    ):
        raise RALValidationError(
            "volume_identity_mismatch", "ACL observations bind another volume"
        )
    candidate = selected.candidate(parsed_plan)
    if not candidate.is_dir():
        raise RALValidationError(
            "registry_candidate_invalid", "candidate root is unavailable"
        )
    facts = _verify_exact_tree(candidate)
    if facts["plan_digest"] != parsed_plan["plan_digest"]:
        raise RALValidationError(
            "root_plan_digest_mismatch", "candidate binds another plan"
        )
    if facts["authority_digest"] != authority["authority_digest"]:
        raise RALValidationError(
            "root_authority_digest_mismatch", "candidate binds another authority"
        )
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-candidate-verification/0.1",
            "verified": True,
            **facts,
            "private_read_count": 0,
            "network_effect_count": 0,
            "external_effect_count": 0,
        },
        "verification_digest",
    )


def _rename_no_replace(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RALValidationError(
            "registry_root_exists", "the final registry root already exists"
        )
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        if not move(str(source), str(destination), 0x8):
            error = ctypes.get_last_error()
            if error in {80, 183}:
                raise RALValidationError(
                    "registry_root_exists", "the final registry root appeared"
                )
            raise RALValidationError(
                "registry_publish_failed", f"no-replace rename failed ({error})"
            )
        return
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RALValidationError(
            "atomic_no_replace_unavailable", "atomic no-replace rename is unavailable"
        )
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == 17:
            raise RALValidationError(
                "registry_root_exists", "the final registry root appeared"
            )
        raise RALValidationError(
            "registry_publish_failed", f"no-replace rename failed ({error})"
        )


def publish_registry_candidate(
    plan: Mapping[str, object],
    verification: Mapping[str, object],
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    parsed_plan = RegistryRootPlan.from_dict(plan).to_dict()
    _verify_bound_receipt(
        verification,
        "verification_digest",
        "candidate_verification_digest_mismatch",
    )
    selected = _storage(storage)
    candidate = selected.candidate(parsed_plan)
    if selected.final.exists():
        raise RALValidationError(
            "registry_root_exists", "the final registry root already exists"
        )
    if not candidate.is_dir():
        raise RALValidationError(
            "registry_candidate_invalid", "candidate root is unavailable"
        )
    if (
        verification.get("verified") is not True
        or verification.get("plan_digest") != parsed_plan["plan_digest"]
    ):
        raise RALValidationError(
            "candidate_verification_mismatch", "verification binds another candidate"
        )
    current_digest = _tree_digest(candidate)
    if current_digest != verification.get("candidate_tree_digest"):
        raise RALValidationError(
            "candidate_tree_digest_mismatch", "candidate changed after verification"
        )
    _rename_no_replace(candidate, selected.final)
    status = registry_root_status(
        expected_plan_digest=str(parsed_plan["plan_digest"]), storage=selected
    )
    if not status["verified"]:
        raise RALValidationError(
            "registry_publication_unverified", "published root did not verify"
        )
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-publication-result/0.1",
            "published": True,
            "registry_id": status["registry_id"],
            "plan_digest": parsed_plan["plan_digest"],
            "manifest_digest": status["manifest_digest"],
            "control_digest": status["control_digest"],
            "tree_digest": status["tree_digest"],
            "ledger_event_count": 0,
            "resident_count": 0,
            "private_read_count": 0,
            "network_effect_count": 0,
            "external_effect_count": 0,
        },
        "publication_digest",
    )


def registry_root_status(
    final_root: str = PRODUCTION_REGISTRY_ROOT,
    expected_plan_digest: str | None = None,
    *,
    storage: RegistryStorage | None = None,
) -> dict[str, object]:
    if final_root != PRODUCTION_REGISTRY_ROOT:
        raise RALValidationError(
            "root_target_mismatch", "status target differs from production root"
        )
    selected = _storage(storage)
    if not selected.final.is_dir() or _is_reparse(selected.final):
        raise RALValidationError(
            "registry_root_unavailable", "the final registry root is unavailable"
        )
    facts = _verify_exact_tree(
        selected.final,
        allow_recovery_material=True,
        allow_extensions=True,
    )
    if (
        expected_plan_digest is not None
        and facts["plan_digest"] != expected_plan_digest
    ):
        raise RALValidationError(
            "root_plan_digest_mismatch", "published root binds another plan"
        )
    status = {
        "schema": "sedb-ral.registry-root-status/0.1",
        "verified": True,
        "registry_id": facts["registry_id"],
        "manifest_digest": facts["manifest_digest"],
        "control_digest": facts["control_digest"],
        "plan_digest": facts["plan_digest"],
        "tree_digest": facts["source_tree_digest"],
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
        "private_read_count": 0,
        "network_effect_count": 0,
        "external_effect_count": 0,
    }
    if (selected.final / "extensions").exists():
        from .production_operations_layout import (
            verify_production_operations_extension,
        )

        extension_status = verify_production_operations_extension(selected.final)
    else:
        from .production_operations_layout import registry_generation_digest

        extension_status = {
            "extensions_status": "absent",
            "activation_receipt_status": "absent",
            "extension_index_digest": None,
            "operations_generation": None,
            "registry_generation_digest": registry_generation_digest(status, None),
            "candidate_id": None,
        }
    return {**status, **extension_status}
