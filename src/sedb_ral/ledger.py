from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from .canonical import (
    CANONICALIZATION_VERSION,
    canonical_bytes,
    loads_strict,
)
from .contracts import validate_contract
from .ctcl import validate_ctcl_receipt
from .errors import RALValidationError

CHAIN_VERSION = "sedb-ral-chain-v1"
_CHAIN_DOMAIN = b"SEDB-RAL-CHAIN-v1\x00"
_CHAIN_PREFIX = f"sha256:{CHAIN_VERSION}:"
_RECORD_PREFIX = "sha256:"
_DRAFT_FIELDS = {
    "schema_version",
    "event_id",
    "ledger_id",
    "event_type",
    "causal_parent_ids",
    "recorded_time_ref",
    "recorded_time",
    "payload",
}
_ANCHOR_FIELDS = {
    "schema_version",
    "ledger_id",
    "ledger_seq",
    "event_count",
    "last_event_id",
    "canonicalization_version",
    "chain_version",
    "final_chain_digest",
}


@dataclass(frozen=True)
class AppendReceipt:
    ledger_seq: int
    event_id: str
    record_digest: str
    chain_digest: str
    event_path: Path
    anchor_path: Path


class LedgerStatus(str, Enum):
    EMPTY = "empty"
    INTERNALLY_CONSISTENT = "internally_consistent"
    CHECKPOINT_VERIFIED = "checkpoint_verified"
    INVALID = "invalid"


@dataclass(frozen=True)
class LedgerVerification:
    valid: bool
    status: LedgerStatus
    event_count: int
    final_chain_digest: str | None
    error_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "status": self.status.value,
            "event_count": self.event_count,
            "final_chain_digest": self.final_chain_digest,
            "error_codes": list(self.error_codes),
        }


def _digest_bytes(reference: str, prefix: str) -> bytes:
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise RALValidationError(
            "digest_reference_invalid", "digest prefix does not match"
        )
    encoded = reference.removeprefix(prefix)
    if len(encoded) != 64:
        raise RALValidationError(
            "digest_reference_invalid", "digest is not 32 bytes"
        )
    try:
        return bytes.fromhex(encoded)
    except ValueError as error:
        raise RALValidationError(
            "digest_reference_invalid", "digest is not lowercase hex"
        ) from error


def _chain_digest(
    previous_chain_digest: str | None,
    record_digest: str,
) -> str:
    previous_raw = (
        bytes(32)
        if previous_chain_digest is None
        else _digest_bytes(previous_chain_digest, _CHAIN_PREFIX)
    )
    record_raw = _digest_bytes(record_digest, _RECORD_PREFIX)
    digest = hashlib.sha256(
        _CHAIN_DOMAIN + previous_raw + record_raw
    ).hexdigest()
    return f"{_CHAIN_PREFIX}{digest}"


def _record_digest(value: Mapping[str, object]) -> str:
    # CHAIN-v1 intentionally hashes canonical event bytes directly. The
    # reference is meaningful only with the event envelope's explicit
    # canonicalization_version; it is not the standalone sha256_ref format.
    digest = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return f"{_RECORD_PREFIX}{digest}"


def _parse_recorded_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RALValidationError(
            "recorded_time_invalid", "recorded time must be explicit UTC"
        )
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise RALValidationError(
            "recorded_time_invalid", "recorded time is not RFC3339 UTC"
        ) from error


def _event_path(root: Path, event: Mapping[str, object]) -> Path:
    instant = _parse_recorded_time(event["recorded_time"])
    return (
        root
        / "events"
        / f"{instant.year:04d}"
        / f"{instant.month:02d}"
        / f"{event['ledger_seq']:020d}-{event['event_id']}.json"
    )


def _anchor_path(root: Path, ledger_seq: int) -> Path:
    return root / "anchors" / f"{ledger_seq:020d}.json"


def _load_object(path: Path) -> tuple[dict[str, object], bool]:
    raw = path.read_bytes()
    value = loads_strict(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RALValidationError("document_not_object", str(path))
    return value, canonical_bytes(value) == raw


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _tree_contains_reparse_point(root: Path) -> bool:
    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, directories, files in os.walk(
        root,
        topdown=True,
        onerror=raise_walk_error,
        followlinks=False,
    ):
        base = Path(current)
        if any(
            _is_reparse_point(base / name)
            for name in [*directories, *files]
        ):
            return True
    return False


def _event_records(
    root: Path,
    errors: list[str] | None = None,
) -> list[tuple[Path, dict[str, object]]]:
    records: list[tuple[Path, dict[str, object]]] = []
    event_root = root / "events"
    if not event_root.exists():
        return records
    try:
        if (
            _is_reparse_point(event_root)
            or not event_root.is_dir()
            or _tree_contains_reparse_point(event_root)
        ):
            if errors is not None:
                errors.append("storage_layout_invalid")
            return records
        entries = sorted(event_root.rglob("*"))
        if errors is not None and any(
            path.is_file() and path.suffix != ".json" for path in entries
        ):
            errors.append("storage_layout_invalid")
        paths = [
            path
            for path in entries
            if path.is_file() and path.suffix == ".json"
        ]
    except OSError:
        if errors is not None:
            errors.append("storage_traversal_failed")
        return records
    for path in paths:
        try:
            if _is_reparse_point(path) or not path.resolve().is_relative_to(
                event_root.resolve()
            ):
                raise RALValidationError(
                    "storage_path_invalid", "event path escapes storage root"
                )
            value, is_canonical = _load_object(path)
            if not is_canonical and errors is not None:
                errors.append("event_not_canonical")
            validate_contract("ledger-event.schema.json", value)
            records.append((path, value))
        except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError):
            if errors is not None:
                errors.append("event_invalid")
    records.sort(key=lambda item: item[1]["ledger_seq"])
    return records


def _validate_anchor(value: Mapping[str, object]) -> None:
    if set(value) != _ANCHOR_FIELDS:
        raise RALValidationError(
            "anchor_invalid", "anchor fields do not match the contract"
        )
    if (
        value["schema_version"] != "0.1"
        or not isinstance(value["ledger_id"], str)
        or type(value["ledger_seq"]) is not int
        or value["ledger_seq"] < 1
        or type(value["event_count"]) is not int
        or value["event_count"] < 1
        or not isinstance(value["last_event_id"], str)
        or value["canonicalization_version"] != CANONICALIZATION_VERSION
        or value["chain_version"] != CHAIN_VERSION
    ):
        raise RALValidationError("anchor_invalid", "anchor value is invalid")
    _digest_bytes(value["final_chain_digest"], _CHAIN_PREFIX)


def _anchor_records(
    root: Path,
    errors: list[str],
) -> list[tuple[Path, dict[str, object]]]:
    records: list[tuple[Path, dict[str, object]]] = []
    anchor_root = root / "anchors"
    if not anchor_root.exists():
        return records
    try:
        if (
            _is_reparse_point(anchor_root)
            or not anchor_root.is_dir()
            or _tree_contains_reparse_point(anchor_root)
        ):
            errors.append("storage_layout_invalid")
            return records
        entries = sorted(anchor_root.iterdir())
        if any(
            path.is_dir() or (path.is_file() and path.suffix != ".json")
            for path in entries
        ):
            errors.append("storage_layout_invalid")
        paths = [
            path
            for path in entries
            if path.is_file() and path.suffix == ".json"
        ]
    except OSError:
        errors.append("storage_traversal_failed")
        return records
    for path in paths:
        try:
            if _is_reparse_point(path) or not path.resolve().is_relative_to(
                anchor_root.resolve()
            ):
                raise RALValidationError(
                    "storage_path_invalid", "anchor path escapes storage root"
                )
            value, is_canonical = _load_object(path)
            if not is_canonical:
                errors.append("anchor_not_canonical")
            _validate_anchor(value)
            records.append((path, value))
        except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError):
            errors.append("anchor_invalid")
    records.sort(key=lambda item: item[1]["ledger_seq"])
    return records


def verify_ledger(
    root: Path,
    *,
    expected_final_chain_digest: str | None = None,
) -> LedgerVerification:
    root = Path(root)
    errors: list[str] = []
    try:
        if root.exists() and (_is_reparse_point(root) or not root.is_dir()):
            errors.append("storage_layout_invalid")
    except OSError:
        errors.append("storage_traversal_failed")
    event_records = _event_records(root, errors)
    event_by_seq: dict[int, dict[str, object]] = {}
    seen_event_ids: set[str] = set()
    expected_previous: str | None = None
    ledger_id: str | None = None

    for expected_seq, (path, event) in enumerate(event_records, start=1):
        sequence = event["ledger_seq"]
        if sequence in event_by_seq:
            errors.append("duplicate_ledger_seq")
        event_by_seq[sequence] = event
        if sequence != expected_seq:
            errors.append("sequence_gap")
        try:
            if path != _event_path(root, event):
                errors.append("filename_sequence_mismatch")
        except RALValidationError:
            errors.append("recorded_time_invalid")

        event_id = event["event_id"]
        if event_id in seen_event_ids:
            errors.append("duplicate_event_id")
        if any(parent not in seen_event_ids for parent in event["causal_parent_ids"]):
            errors.append("causal_parent_missing")

        if ledger_id is None:
            ledger_id = event["ledger_id"]
        elif event["ledger_id"] != ledger_id:
            errors.append("ledger_id_mismatch")

        body = dict(event)
        integrity = body.pop("integrity")
        computed_record = _record_digest(body)
        if integrity["record_digest"] != computed_record:
            errors.append("record_digest_mismatch")
        if integrity["previous_chain_digest"] != expected_previous:
            errors.append("previous_chain_digest_mismatch")
        computed_chain = _chain_digest(expected_previous, computed_record)
        if integrity["chain_digest"] != computed_chain:
            errors.append("chain_digest_mismatch")
        expected_previous = computed_chain
        seen_event_ids.add(event_id)

    anchor_records = _anchor_records(root, errors)
    anchor_by_seq: dict[int, tuple[Path, dict[str, object]]] = {}
    for path, anchor in anchor_records:
        sequence = anchor["ledger_seq"]
        if sequence in anchor_by_seq:
            errors.append("duplicate_anchor_sequence")
        anchor_by_seq[sequence] = (path, anchor)
        if path != _anchor_path(root, sequence):
            errors.append("anchor_filename_mismatch")

    for sequence, event in event_by_seq.items():
        record = anchor_by_seq.get(sequence)
        if record is None:
            errors.append("anchor_missing")
            continue
        _, anchor = record
        if anchor["event_count"] != sequence:
            errors.append("anchor_count_mismatch")
        if anchor["ledger_id"] != event["ledger_id"]:
            errors.append("anchor_ledger_mismatch")
        if anchor["last_event_id"] != event["event_id"]:
            errors.append("anchor_event_mismatch")
        if anchor["final_chain_digest"] != event["integrity"]["chain_digest"]:
            errors.append("anchor_digest_mismatch")

    for sequence in anchor_by_seq:
        if sequence not in event_by_seq:
            errors.append("anchored_event_missing")

    if expected_final_chain_digest is not None:
        try:
            _digest_bytes(expected_final_chain_digest, _CHAIN_PREFIX)
        except RALValidationError:
            errors.append("external_anchor_invalid")
        else:
            if expected_previous != expected_final_chain_digest:
                errors.append("external_anchor_mismatch")

    unique_errors = tuple(sorted(set(errors)))
    if unique_errors:
        status = LedgerStatus.INVALID
    elif not event_records:
        status = LedgerStatus.EMPTY
    elif expected_final_chain_digest is None:
        status = LedgerStatus.INTERNALLY_CONSISTENT
    else:
        status = LedgerStatus.CHECKPOINT_VERIFIED
    return LedgerVerification(
        valid=status is LedgerStatus.CHECKPOINT_VERIFIED,
        status=status,
        event_count=len(event_records),
        final_chain_digest=expected_previous,
        error_codes=unique_errors,
    )


def _validate_draft(draft: Mapping[str, object]) -> None:
    if set(draft) != _DRAFT_FIELDS:
        raise RALValidationError(
            "event_draft_invalid", "event draft fields do not match"
        )
    candidate = dict(draft)
    candidate["ledger_seq"] = 1
    candidate["integrity"] = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "chain_version": CHAIN_VERSION,
        "record_digest": _RECORD_PREFIX + "0" * 64,
        "previous_chain_digest": None,
        "chain_digest": _CHAIN_PREFIX + "0" * 64,
    }
    validate_contract("ledger-event.schema.json", candidate)
    _parse_recorded_time(draft["recorded_time"])


@contextmanager
def _exclusive_append(root: Path) -> Iterator[None]:
    try:
        root.mkdir(parents=True, exist_ok=True)
    except FileExistsError as error:
        raise RALValidationError(
            "storage_layout_invalid", "ledger root is not a directory"
        ) from error
    except OSError as error:
        raise RALValidationError(
            "append_lock_failed", f"cannot create ledger root: {error}"
        ) from error
    try:
        if _is_reparse_point(root) or not root.is_dir():
            raise RALValidationError(
                "storage_layout_invalid",
                "ledger root must be a real directory",
            )
    except RALValidationError:
        raise
    except OSError as error:
        raise RALValidationError(
            "append_lock_failed", f"cannot inspect ledger root: {error}"
        ) from error

    lock = root / ".append.lock"
    lock_created = False
    try:
        with lock.open("xb") as stream:
            lock_created = True
            stream.write(str(os.getpid()).encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise RALValidationError(
            "append_in_progress", "ledger append lock already exists"
        ) from error
    except OSError as error:
        if lock_created:
            try:
                lock.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise RALValidationError(
                    "append_lock_failed",
                    f"lock setup failed and cleanup failed: {cleanup_error}",
                ) from error
        raise RALValidationError(
            "append_lock_failed", f"lock setup failed: {error}"
        ) from error
    try:
        yield
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError as error:
            raise RALValidationError(
                "append_lock_cleanup_failed", str(error)
            ) from error


def _publish_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as error:
        raise RALValidationError(
            "immutable_path_exists", str(path)
        ) from error
    except OSError as error:
        raise RALValidationError(
            "immutable_publish_failed", f"{type(error).__name__}: {path}"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def append_event(
    root: Path,
    draft: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    *,
    expected_previous_chain_digest: str | None,
) -> AppendReceipt:
    root = Path(root)
    _validate_draft(draft)
    validate_ctcl_receipt(ctcl_receipt)
    if ctcl_receipt["ctcl_call_kind"] != "registered_anchor":
        raise RALValidationError(
            "registered_anchor_required",
            "recorded_time requires a registered CTCL anchor",
        )
    if ctcl_receipt["ctcl_instant_id"] != draft["recorded_time_ref"]:
        raise RALValidationError(
            "recorded_time_ref_mismatch",
            "event and CTCL anchor IDs differ",
        )
    if ctcl_receipt["reference"]["value"] != draft["recorded_time"]:
        raise RALValidationError(
            "recorded_time_mismatch",
            "event and CTCL anchor times differ",
        )

    with _exclusive_append(root):
        verification = verify_ledger(
            root,
            expected_final_chain_digest=expected_previous_chain_digest,
        )
        if verification.status is LedgerStatus.INVALID:
            raise RALValidationError(
                "ledger_invalid",
                ",".join(verification.error_codes),
            )
        if (
            verification.status is LedgerStatus.INTERNALLY_CONSISTENT
            and expected_previous_chain_digest is None
        ):
            raise RALValidationError(
                "genesis_conflicts_with_existing_ledger",
                "an existing ledger requires its externally retained head",
            )
        existing = _event_records(root)
        event_ids = {event["event_id"] for _, event in existing}
        if draft["event_id"] in event_ids:
            raise RALValidationError(
                "duplicate_event_id", str(draft["event_id"])
            )
        if existing and draft["ledger_id"] != existing[0][1]["ledger_id"]:
            raise RALValidationError(
                "ledger_id_mismatch", "cannot mix ledger IDs"
            )
        missing_parents = [
            parent
            for parent in draft["causal_parent_ids"]
            if parent not in event_ids
        ]
        if missing_parents:
            raise RALValidationError(
                "causal_parent_missing", ",".join(missing_parents)
            )

        ledger_seq = len(existing) + 1
        previous_chain = (
            None
            if not existing
            else existing[-1][1]["integrity"]["chain_digest"]
        )
        body = dict(draft)
        body["ledger_seq"] = ledger_seq
        record_digest = _record_digest(body)
        chain_digest = _chain_digest(previous_chain, record_digest)
        event = dict(body)
        event["integrity"] = {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "chain_version": CHAIN_VERSION,
            "record_digest": record_digest,
            "previous_chain_digest": previous_chain,
            "chain_digest": chain_digest,
        }
        validate_contract("ledger-event.schema.json", event)

        event_path = _event_path(root, event)
        anchor_path = _anchor_path(root, ledger_seq)
        anchor = {
            "schema_version": "0.1",
            "ledger_id": draft["ledger_id"],
            "ledger_seq": ledger_seq,
            "event_count": ledger_seq,
            "last_event_id": draft["event_id"],
            "canonicalization_version": CANONICALIZATION_VERSION,
            "chain_version": CHAIN_VERSION,
            "final_chain_digest": chain_digest,
        }
        _validate_anchor(anchor)

        _publish_immutable(event_path, canonical_bytes(event))
        try:
            _publish_immutable(anchor_path, canonical_bytes(anchor))
        except RALValidationError as error:
            raise RALValidationError(
                "anchor_publish_failed", str(error)
            ) from error

    return AppendReceipt(
        ledger_seq=ledger_seq,
        event_id=draft["event_id"],
        record_digest=record_digest,
        chain_digest=chain_digest,
        event_path=event_path,
        anchor_path=anchor_path,
    )
