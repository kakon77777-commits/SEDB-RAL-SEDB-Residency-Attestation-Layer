from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .application import authority_digest
from .authority import validate_authority
from .canonical import canonical_bytes, loads_strict
from .contracts import validate_contract
from .errors import RALValidationError


@dataclass(frozen=True)
class RegistryProjection:
    applications: dict[str, dict[str, object]]
    residents: dict[str, dict[str, object]]
    directory: dict[str, dict[str, object]]
    claims: dict[str, dict[str, object]]
    resident_source_event_ids: dict[str, str]
    applied_corrections: tuple[str, ...]
    unapplied_event_ids: tuple[str, ...]
    unapplied_reasons: dict[str, str]
    source_event_ids: tuple[str, ...]
    attestations: dict[str, tuple[dict[str, object], ...]] = field(
        default_factory=dict
    )


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
    resident_claim_owners: dict[str, str] = {}
    attestations: dict[str, list[dict[str, object]]] = {}
    resident_source_event_ids: dict[str, str] = {}
    authority_grants: dict[str, tuple[str, str]] = {}
    revoked_authority_grants: set[str] = set()
    event_entities: dict[str, set[tuple[str, str]]] = {}
    corrections: list[str] = []
    unapplied: list[str] = []
    unapplied_reasons: dict[str, str] = {}
    source_ids: list[str] = []

    def mark_unapplied(event_id: str, reason: str) -> None:
        unapplied.append(event_id)
        unapplied_reasons[event_id] = reason

    for event in sorted(events, key=lambda item: item["ledger_seq"]):
        event_id = str(event["event_id"])
        event_type = event["event_type"]
        payload = event["payload"]
        source_ids.append(event_id)
        event_entities[event_id] = set()

        if event_type == "authority.granted":
            try:
                authority = _copy(payload["authority"])
                validate_authority(authority)
                digest = authority_digest(authority)
                if (
                    payload.get("authority_digest") != digest
                    or payload.get("authorship_attestation_ref")
                    != authority["authorship_attestation_ref"]
                    or payload.get("authorship_verification_status") != "verified"
                ):
                    raise RALValidationError(
                        "authority_grant_invalid", "grant evidence does not match"
                    )
            except (KeyError, TypeError, RALValidationError):
                mark_unapplied(event_id, "authority_grant_invalid")
                continue
            authority_id = str(authority["authority_id"])
            authority_grants[event_id] = (authority_id, digest)
            event_entities[event_id].add(("authority", authority_id))
            continue

        if event_type == "application.submitted":
            application = _copy(payload["application"])
            application["application_digest"] = payload["application_digest"]
            application["status"] = "submitted"
            application_id = str(application["application_id"])
            applications[application_id] = application
            event_entities[event_id].add(("application", application_id))
            continue

        if event_type == "application.accepted":
            application_id = str(payload["application_id"])
            application = applications.get(application_id)
            if application is None:
                mark_unapplied(event_id, "application_submission_missing")
                continue
            grant_event_id = payload.get("authority_grant_event_id")
            grant = authority_grants.get(grant_event_id)
            if grant is None:
                mark_unapplied(event_id, "application_authority_grant_missing")
                continue
            if grant_event_id in revoked_authority_grants:
                mark_unapplied(event_id, "application_authority_grant_revoked")
                continue
            if grant != (
                payload.get("authority_id"),
                payload.get("authority_digest"),
            ):
                mark_unapplied(event_id, "application_authority_grant_mismatch")
                continue
            if payload.get("application_digest") != application.get(
                "application_digest"
            ):
                mark_unapplied(event_id, "application_digest_mismatch")
                continue
            application["status"] = "accepted"
            application["authority_ref"] = payload["authority_id"]
            application["authority_digest"] = payload["authority_digest"]
            application["authority_grant_event_id"] = payload[
                "authority_grant_event_id"
            ]
            application["decision_ref"] = payload["decision_ref"]
            event_entities[event_id].add(("application", application_id))
            continue

        if event_type == "resident.registered":
            resident = _copy(payload["resident"])
            application = applications.get(resident["application_ref"])
            if application is None or application.get("status") != "accepted":
                mark_unapplied(event_id, "resident_registration_not_authorized")
                continue
            grant_event_id = application.get("authority_grant_event_id")
            if (
                authority_grants.get(grant_event_id)
                == (
                    application.get("authority_ref"),
                    application.get("authority_digest"),
                )
                and grant_event_id in revoked_authority_grants
            ):
                mark_unapplied(
                    event_id, "resident_registration_authority_revoked"
                )
                continue
            if application["claimed_resident_id"] != resident["resident_id"]:
                mark_unapplied(
                    event_id, "resident_registration_application_mismatch"
                )
                continue
            resident["instances"] = _copy(payload["instances"])
            resident["addresses"] = _copy(payload["addresses"])
            resident["claims"] = _copy(payload["claims"])
            resident_id = str(resident["resident_id"])
            residents[resident_id] = resident
            attestations.setdefault(resident_id, [])
            resident_source_event_ids[resident_id] = event_id
            event_entities[event_id].add(("resident", resident_id))
            for instance in resident["instances"]:
                event_entities[event_id].add(
                    ("instance", str(instance["instance_id"]))
                )
            for address in resident["addresses"]:
                event_entities[event_id].add(
                    ("address", str(address["address_id"]))
                )
            for claim in resident["claims"]:
                claim_id = str(claim["claim_id"])
                claims[claim_id] = claim
                resident_claim_owners[claim_id] = resident_id
                event_entities[event_id].add(("claim", claim_id))
            continue

        if event_type == "claim.recorded":
            claim = _copy(payload["claim"])
            validate_contract("claim.schema.json", claim)
            claim_id = str(claim["claim_id"])
            claims[claim_id] = claim
            event_entities[event_id].add(("claim", claim_id))
            continue

        if event_type == "attestation.recorded":
            try:
                attestation = _copy(payload["attestation"])
                validate_contract("attestation.schema.json", attestation)
            except (KeyError, TypeError, RALValidationError):
                mark_unapplied(event_id, "attestation_contract_invalid")
                continue
            claim_ref = str(attestation["claim_ref"])
            if claim_ref not in claims:
                mark_unapplied(event_id, "attestation_claim_missing")
                continue
            resident_id = resident_claim_owners.get(claim_ref)
            if resident_id is None:
                mark_unapplied(event_id, "attestation_claim_unowned")
                continue
            attestations[resident_id].append(attestation)
            event_entities[event_id].add(
                ("attestation", str(attestation["attestation_id"]))
            )
            continue

        if event_type == "authority.revoked":
            authority_id = payload.get("authority_id")
            if isinstance(authority_id, str):
                event_entities[event_id].add(("authority", authority_id))
            grant_event_id = payload.get("authority_grant_event_id")
            if authority_grants.get(grant_event_id) == (
                authority_id,
                payload.get("authority_digest"),
            ):
                revoked_authority_grants.add(grant_event_id)
            continue

        if event_type == "record.corrected":
            correction = payload.get("correction")
            try:
                validate_contract("correction-tombstone.schema.json", correction)
            except RALValidationError:
                mark_unapplied(event_id, "correction_contract_invalid")
                continue
            target_event_id = correction["target_event_id"]
            target_kind = payload.get("target_kind")
            target_ref = payload.get("target_ref")
            if target_event_id not in event_entities:
                mark_unapplied(event_id, "correction_target_event_missing")
                continue
            target = (target_kind, target_ref)
            if target not in event_entities[target_event_id]:
                exists_elsewhere = any(
                    target in entities for entities in event_entities.values()
                )
                mark_unapplied(
                    event_id,
                    "correction_target_event_mismatch"
                    if exists_elsewhere
                    else "correction_target_entity_mismatch",
                )
                continue

            action = correction["action"]
            if action == "correct":
                if (
                    set(payload)
                    != {"correction", "target_kind", "target_ref", "changes"}
                    or target_kind != "resident"
                    or target_ref not in residents
                ):
                    mark_unapplied(event_id, "correction_payload_unsupported")
                    continue
                changes = payload["changes"]
                if (
                    not isinstance(changes, Mapping)
                    or set(changes) != {"display_label"}
                    or not isinstance(changes["display_label"], str)
                    or not changes["display_label"]
                ):
                    mark_unapplied(event_id, "correction_payload_unsupported")
                    continue
                replacement = claims.get(correction["replacement_ref"])
                if replacement is None:
                    mark_unapplied(event_id, "correction_replacement_missing")
                    continue
                if (
                    replacement["subject_ref"] != target_ref
                    or replacement["predicate"] != "display_label"
                    or replacement["object"] != changes["display_label"]
                ):
                    mark_unapplied(event_id, "correction_replacement_mismatch")
                    continue
                residents[target_ref]["display_label"] = changes["display_label"]
                corrections.append(correction["correction_id"])
                event_entities[event_id].add(
                    ("correction", correction["correction_id"])
                )
                continue

            if action in {"withdraw", "tombstone"}:
                if (
                    set(payload) != {"correction", "target_kind", "target_ref"}
                    or correction["replacement_ref"] is not None
                    or target_kind != "resident"
                    or target_ref not in residents
                ):
                    mark_unapplied(event_id, "correction_payload_unsupported")
                    continue
                residents[target_ref]["status"] = (
                    "withdrawn" if action == "withdraw" else "tombstoned"
                )
                corrections.append(correction["correction_id"])
                event_entities[event_id].add(
                    ("correction", correction["correction_id"])
                )
                continue

            mark_unapplied(event_id, "correction_action_unsupported")
            continue

        mark_unapplied(event_id, "event_type_unsupported")

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
        resident_source_event_ids=resident_source_event_ids,
        applied_corrections=tuple(corrections),
        unapplied_event_ids=tuple(unapplied),
        unapplied_reasons=unapplied_reasons,
        source_event_ids=tuple(source_ids),
        attestations={
            resident_id: tuple(
                sorted(values, key=lambda value: str(value["attestation_id"]))
            )
            for resident_id, values in sorted(attestations.items())
            if resident_id in residents
        },
    )


def write_projection(
    projection: RegistryProjection,
    output: Path,
) -> tuple[Path, ...]:
    output = Path(output)
    if output.exists():
        if not output.is_dir():
            raise RALValidationError(
                "projection_output_not_directory", str(output)
            )
        if any(output.iterdir()):
            raise RALValidationError("projection_output_not_empty", str(output))
    else:
        output.mkdir(parents=True)
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
    directory_path.write_bytes(
        canonical_bytes(
            {
                "residents": projection.directory,
                "resident_source_event_ids": projection.resident_source_event_ids,
                "source_event_ids": list(projection.source_event_ids),
                "applied_corrections": list(projection.applied_corrections),
                "unapplied_event_ids": list(projection.unapplied_event_ids),
                "unapplied_reasons": projection.unapplied_reasons,
            }
        )
    )
    paths.append(directory_path)
    return tuple(
        sorted(paths, key=lambda path: path.relative_to(output).as_posix())
    )


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
