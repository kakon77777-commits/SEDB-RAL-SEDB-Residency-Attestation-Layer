from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .canonical import canonical_bytes, loads_strict
from .contracts import validate_contract


@dataclass(frozen=True)
class RegistryProjection:
    applications: dict[str, dict[str, object]]
    residents: dict[str, dict[str, object]]
    directory: dict[str, dict[str, object]]
    claims: dict[str, dict[str, object]]
    applied_corrections: tuple[str, ...]
    unapplied_event_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]


def _copy(value: object) -> object:
    return loads_strict(canonical_bytes(value).decode("utf-8"))


def _safe_name(value: str) -> str:
    return quote(value, safe="._-")


def project_events(
    events: Iterable[Mapping[str, object]],
) -> RegistryProjection:
    applications: dict[str, dict[str, object]] = {}
    residents: dict[str, dict[str, object]] = {}
    claims: dict[str, dict[str, object]] = {}
    corrections: list[str] = []
    unapplied: list[str] = []
    source_ids: list[str] = []

    for event in sorted(events, key=lambda item: item["ledger_seq"]):
        event_id = str(event["event_id"])
        event_type = event["event_type"]
        payload = event["payload"]
        source_ids.append(event_id)
        if event_type == "application.submitted":
            application = _copy(payload["application"])
            application["application_digest"] = payload["application_digest"]
            application["status"] = "submitted"
            applications[application["application_id"]] = application
        elif event_type == "application.accepted":
            application = applications.get(payload["application_id"])
            if application is None:
                unapplied.append(event_id)
                continue
            application["status"] = "accepted"
            application["authority_ref"] = payload["authority_ref"]
            application["decision_ref"] = payload["decision_ref"]
        elif event_type == "resident.registered":
            resident = _copy(payload["resident"])
            resident["instances"] = _copy(payload["instances"])
            resident["addresses"] = _copy(payload["addresses"])
            resident["claims"] = _copy(payload["claims"])
            residents[resident["resident_id"]] = resident
            for claim in resident["claims"]:
                claims[claim["claim_id"]] = claim
        elif event_type == "record.corrected":
            correction = payload["correction"]
            validate_contract("correction-tombstone.schema.json", correction)
            if (
                payload.get("target_kind") != "resident"
                or payload.get("target_ref") not in residents
            ):
                unapplied.append(event_id)
                continue
            changes = payload.get("changes")
            if not isinstance(changes, dict) or set(changes) != {"display_label"}:
                unapplied.append(event_id)
                continue
            residents[payload["target_ref"]]["display_label"] = changes[
                "display_label"
            ]
            corrections.append(correction["correction_id"])
        else:
            unapplied.append(event_id)

    directory = {
        resident_id: {
            "display_label": value["display_label"],
            "status": value["status"],
            "addresses": _copy(value["addresses"]),
            "instance_refs": sorted(
                item["instance_id"] for item in value["instances"]
            ),
        }
        for resident_id, value in sorted(residents.items())
    }
    return RegistryProjection(
        applications=applications,
        residents=residents,
        directory=directory,
        claims=claims,
        applied_corrections=tuple(corrections),
        unapplied_event_ids=tuple(unapplied),
        source_event_ids=tuple(source_ids),
    )


def write_projection(
    projection: RegistryProjection,
    output: Path,
) -> tuple[Path, ...]:
    output = Path(output)
    paths: list[Path] = []
    for category, values in (
        ("applications", projection.applications),
        ("residents", projection.residents),
    ):
        directory = output / category
        directory.mkdir(parents=True, exist_ok=True)
        for item_id, value in sorted(values.items()):
            path = directory / f"{_safe_name(item_id)}.json"
            path.write_bytes(canonical_bytes(value))
            paths.append(path)
    directory_path = output / "directory.json"
    directory_path.parent.mkdir(parents=True, exist_ok=True)
    directory_path.write_bytes(
        canonical_bytes(
            {
                "residents": projection.directory,
                "source_event_ids": list(projection.source_event_ids),
                "applied_corrections": list(projection.applied_corrections),
                "unapplied_event_ids": list(projection.unapplied_event_ids),
            }
        )
    )
    paths.append(directory_path)
    return tuple(sorted(paths, key=lambda path: path.relative_to(output).as_posix()))


def _byte_map(paths: tuple[Path, ...]) -> dict[str, bytes]:
    if not paths:
        return {}
    root = Path(os.path.commonpath([str(path) for path in paths]))
    if root.is_file():
        root = root.parent
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in paths
    }


def compare_projection_bytes(
    first: tuple[Path, ...],
    second: tuple[Path, ...],
) -> tuple[str, ...]:
    left = _byte_map(first)
    right = _byte_map(second)
    errors = []
    if set(left) != set(right):
        errors.append("projection_path_set_mismatch")
    if any(left.get(path) != right.get(path) for path in set(left) | set(right)):
        errors.append("projection_mismatch")
    return tuple(errors)
