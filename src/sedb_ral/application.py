from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from .authority import authority_matches_subject, validate_authority
from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .ledger import AppendReceipt, append_event, read_verified_events


@dataclass(frozen=True)
class ApplicationDecision:
    decision: str
    reason_codes: tuple[str, ...]
    application_digest: str
    authority_ref: str | None
    mutated: bool = False

    def as_json(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "application_digest": self.application_digest,
            "authority_ref": self.authority_ref,
            "mutated": self.mutated,
        }


@dataclass(frozen=True)
class ApplicationCommitReceipt:
    decision_ref: str
    application_digest: str
    authority_ref: str
    authority_digest: str
    authority_grant_event_id: str
    event_ids: tuple[str, ...]
    chain_digest: str
    committed: bool = True


@dataclass(frozen=True)
class _AuthorityGrant:
    authority: dict[str, object]
    authority_digest: str
    grant_event_id: str


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    normalized = loads_strict(canonical_bytes(value).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise TypeError("canonical application must remain an object")
    return normalized


def application_digest(value: Mapping[str, object]) -> str:
    return sha256_ref(_canonical_object(value))


def authority_digest(value: Mapping[str, object]) -> str:
    return sha256_ref(_canonical_object(value))


def _has_duplicate_id(
    values: Iterable[Mapping[str, object]], field: str
) -> bool:
    identifiers = [item[field] for item in values]
    return len(identifiers) != len(set(identifiers))


def validate_application_references(
    application: Mapping[str, object],
) -> tuple[str, ...]:
    """Return deterministic cross-reference failures without mutating input."""
    resident_id = application["claimed_resident_id"]
    instances = application["instance_claims"]
    addresses = application["addresses"]
    claims = application["claims"]
    instance_ids = {item["instance_id"] for item in instances}
    errors: list[str] = []
    if any(item["resident_ref"] != resident_id for item in instances):
        errors.append("application_instance_resident_mismatch")
    if any(item["target_ref"] != resident_id for item in addresses):
        errors.append("application_address_target_mismatch")
    if any(item["subject_ref"] != resident_id for item in claims):
        errors.append("application_claim_subject_mismatch")
    if any(item["claimant_ref"] != resident_id for item in claims):
        errors.append("application_claim_claimant_mismatch")
    if any(
        item["claimed_authored_by_instance"] is not None
        and item["claimed_authored_by_instance"] not in instance_ids
        for item in claims
    ):
        errors.append("application_claim_instance_undeclared")
    if any(item["claimed_on_behalf_of_line"] is not None for item in claims):
        errors.append("application_on_behalf_unsupported")
    if _has_duplicate_id(instances, "instance_id"):
        errors.append("application_instance_id_duplicate")
    if _has_duplicate_id(addresses, "address_id"):
        errors.append("application_address_id_duplicate")
    if _has_duplicate_id(claims, "claim_id"):
        errors.append("application_claim_id_duplicate")
    return tuple(errors)


def _decision(
    value: Mapping[str, object],
    decision: str,
    code: str,
    authority_ref: str | None = None,
) -> ApplicationDecision:
    return ApplicationDecision(
        decision=decision,
        reason_codes=(code,),
        application_digest=application_digest(value),
        authority_ref=authority_ref,
    )


def evaluate_application(
    application: Mapping[str, object],
    authorities: Iterable[Mapping[str, object]],
    *,
    verified_attestation_refs: Set[str],
) -> ApplicationDecision:
    application = _canonical_object(application)
    validate_contract("application.schema.json", application)
    reference_errors = validate_application_references(application)
    if reference_errors:
        return _decision(application, "defer", reference_errors[0])
    digest = application_digest(application)
    resident_id = application["claimed_resident_id"]
    requested_scopes = set(application["requested_scopes"])
    acceptance_scope = "registry.application.accept"
    if acceptance_scope not in requested_scopes:
        return _decision(application, "defer", "authority_scope_missing")

    matching = []
    for authority in authorities:
        authority = _canonical_object(authority)
        validate_authority(authority)
        if authority_matches_subject(
            authority,
            application_digest=digest,
            resident_id=resident_id,
        ):
            matching.append(authority)
    if not matching:
        return _decision(application, "defer", "authority_missing")

    active = [item for item in matching if item["status"] == "active"]
    if not active:
        if any(item["status"] == "revoked" for item in matching):
            return _decision(application, "defer", "authority_revoked")
        return _decision(application, "defer", "authority_unavailable")
    if len(active) > 1:
        return _decision(application, "defer", "authority_ambiguous")

    authority = active[0]
    authority_ref = authority["authority_id"]
    if acceptance_scope not in set(authority["scopes"]):
        return _decision(
            application,
            "defer",
            "authority_scope_missing",
            authority_ref,
        )
    if not requested_scopes.issubset(set(authority["scopes"])):
        return _decision(
            application,
            "defer",
            "authority_scope_missing",
            authority_ref,
        )
    if authority["authorship_attestation_ref"] not in verified_attestation_refs:
        return _decision(
            application,
            "defer",
            "authority_authorship_unverified",
            authority_ref,
        )
    return _decision(
        application,
        "accept",
        "authority_sufficient",
        authority_ref,
    )


def _event_draft(
    *,
    event_id: str,
    event_type: str,
    parent_ids: tuple[str, ...],
    recorded_time_ref: str,
    recorded_time: str,
    payload: Mapping[str, object],
    ledger_id: str,
) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "event_id": event_id,
        "ledger_id": ledger_id,
        "event_type": event_type,
        "causal_parent_ids": list(parent_ids),
        "recorded_time_ref": recorded_time_ref,
        "recorded_time": recorded_time,
        "payload": dict(payload),
    }


def _existing_context(
    root: Path,
    expected_head: str | None,
) -> tuple[str, tuple[str, ...]]:
    if expected_head is None:
        return "ledger:registry", ()
    events = read_verified_events(root, expected_head)
    if not events:
        raise RALValidationError(
            "external_anchor_mismatch", "expected a non-empty ledger"
        )
    return events[-1]["ledger_id"], (events[-1]["event_id"],)


def commit_application(
    root: Path,
    application: Mapping[str, object],
    decision: ApplicationDecision,
    authority: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    *,
    expected_head: str | None,
    verified_attestation_refs: Set[str],
) -> ApplicationCommitReceipt:
    application = _canonical_object(application)
    digest = application_digest(application)
    if decision.decision != "accept":
        raise RALValidationError(
            "decision_not_accepted", "application decision is not accept"
        )
    if decision.application_digest != digest:
        raise RALValidationError(
            "application_digest_stale", "application changed after decision"
        )
    fresh = evaluate_application(
        application,
        [authority],
        verified_attestation_refs=verified_attestation_refs,
    )
    if fresh.decision != "accept":
        raise RALValidationError(
            fresh.reason_codes[0], "authority failed commit-time revalidation"
        )
    if fresh.authority_ref != decision.authority_ref:
        raise RALValidationError(
            "authority_basis_stale", "decision authority changed"
        )

    existing_events = (
        ()
        if expected_head is None
        else read_verified_events(Path(root), expected_head)
    )
    grants = _project_authority_grants(existing_events)
    canonical_authority = _canonical_object(authority)
    grant_digest = authority_digest(canonical_authority)
    authority_id = canonical_authority["authority_id"]
    existing_grant = grants.get(authority_id)
    if (
        existing_grant is not None
        and existing_grant.authority_digest != grant_digest
    ):
        raise RALValidationError(
            "authority_grant_conflict",
            "authority ID is already bound to different canonical content",
        )
    if existing_grant is not None and existing_grant.authority["status"] != "active":
        raise RALValidationError(
            "authority_revoked", "only an active canonical grant can authorize"
        )

    ledger_id, first_parents = _existing_context(Path(root), expected_head)
    recorded_time_ref = ctcl_receipt["ctcl_instant_id"]
    recorded_time = ctcl_receipt["reference"]["value"]
    suffix = digest.rsplit(":", 1)[-1][:16]
    authority_suffix = grant_digest.rsplit(":", 1)[-1][:16]
    grant_event_id = (
        existing_grant.grant_event_id
        if existing_grant is not None
        else f"evt_authority_granted_{authority_suffix}"
    )
    decision_ref = f"decision:application:{suffix}"
    event_specs: list[tuple[str, str, dict[str, object]]] = []
    if existing_grant is None:
        event_specs.append(
            (
                grant_event_id,
                "authority.granted",
                {
                    "authority": canonical_authority,
                    "authority_digest": grant_digest,
                    "authorship_attestation_ref": canonical_authority[
                        "authorship_attestation_ref"
                    ],
                    "authorship_verification_status": "verified",
                },
            )
        )
    event_specs.extend(
        (
        (
            f"evt_application_submitted_{suffix}",
            "application.submitted",
            {
                "application": application,
                "application_digest": digest,
                "decision": decision.as_json(),
            },
        ),
        (
            f"evt_application_accepted_{suffix}",
            "application.accepted",
            {
                "application_id": application["application_id"],
                "application_digest": digest,
                "authority_id": fresh.authority_ref,
                "authority_digest": grant_digest,
                "authority_grant_event_id": grant_event_id,
                "decision_ref": decision_ref,
            },
        ),
        (
            f"evt_resident_registered_{suffix}",
            "resident.registered",
            {
                "resident": {
                    "schema_version": "0.1",
                    "resident_id": application["claimed_resident_id"],
                    "display_label": application["display_label"],
                    "status": "active",
                    "application_ref": application["application_id"],
                    "identifier_refs": [],
                },
                "instances": application["instance_claims"],
                "addresses": application["addresses"],
                "claims": application["claims"],
            },
        ),
        )
    )
    previous = expected_head
    parents = first_parents
    receipts: list[AppendReceipt] = []
    for event_id, event_type, payload in event_specs:
        receipt = append_event(
            Path(root),
            _event_draft(
                event_id=event_id,
                event_type=event_type,
                parent_ids=parents,
                recorded_time_ref=recorded_time_ref,
                recorded_time=recorded_time,
                payload=payload,
                ledger_id=ledger_id,
            ),
            ctcl_receipt,
            expected_previous_chain_digest=previous,
        )
        receipts.append(receipt)
        previous = receipt.chain_digest
        parents = (receipt.event_id,)
    return ApplicationCommitReceipt(
        decision_ref=decision_ref,
        application_digest=digest,
        authority_ref=fresh.authority_ref or "",
        authority_digest=grant_digest,
        authority_grant_event_id=grant_event_id,
        event_ids=tuple(item.event_id for item in receipts),
        chain_digest=receipts[-1].chain_digest,
    )


def revoke_authority(
    root: Path,
    authority: Mapping[str, object],
    revocation: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    *,
    expected_head: str,
) -> AppendReceipt:
    authority = _canonical_object(authority)
    validate_authority(authority)
    required = {"revocation_id", "authority_id", "reason"}
    if set(revocation) != required:
        raise RALValidationError(
            "revocation_invalid", "revocation fields do not match"
        )
    if revocation["authority_id"] != authority["authority_id"]:
        raise RALValidationError(
            "revocation_authority_mismatch", "authority IDs differ"
        )
    if authority["status"] != "active":
        raise RALValidationError(
            "authority_revoked", "only active authority can be revoked"
        )
    existing_events = read_verified_events(Path(root), expected_head)
    grants = _project_authority_grants(existing_events)
    grant = grants.get(authority["authority_id"])
    if grant is None:
        raise RALValidationError(
            "authority_grant_missing", "authority has no canonical grant event"
        )
    if grant.authority_digest != authority_digest(authority):
        raise RALValidationError(
            "authority_grant_conflict", "authority differs from canonical grant"
        )
    if grant.authority["status"] != "active":
        raise RALValidationError(
            "authority_revoked", "only active authority can be revoked"
        )
    ledger_id, parents = _existing_context(Path(root), expected_head)
    suffix = sha256_ref(revocation).rsplit(":", 1)[-1][:16]
    event_id = f"evt_authority_revoked_{suffix}"
    return append_event(
        Path(root),
        _event_draft(
            event_id=event_id,
            event_type="authority.revoked",
            parent_ids=parents,
            recorded_time_ref=ctcl_receipt["ctcl_instant_id"],
            recorded_time=ctcl_receipt["reference"]["value"],
            payload={
                "authority_id": authority["authority_id"],
                "authority_digest": grant.authority_digest,
                "authority_grant_event_id": grant.grant_event_id,
                "revocation": dict(revocation),
            },
            ledger_id=ledger_id,
        ),
        ctcl_receipt,
        expected_previous_chain_digest=expected_head,
    )


def _project_authority_grants(
    events: Iterable[Mapping[str, object]],
) -> dict[str, _AuthorityGrant]:
    grants: dict[str, _AuthorityGrant] = {}
    for event in sorted(events, key=lambda item: item["ledger_seq"]):
        event_type = event["event_type"]
        payload = event["payload"]
        if event_type == "authority.granted":
            expected_fields = {
                "authority",
                "authority_digest",
                "authorship_attestation_ref",
                "authorship_verification_status",
            }
            if set(payload) != expected_fields:
                raise RALValidationError(
                    "authority_grant_invalid", "grant payload fields differ"
                )
            authority = _canonical_object(payload["authority"])
            validate_authority(authority)
            digest = authority_digest(authority)
            if payload["authority_digest"] != digest:
                raise RALValidationError(
                    "authority_grant_digest_mismatch",
                    "authority snapshot does not match its digest",
                )
            if (
                payload["authorship_attestation_ref"]
                != authority["authorship_attestation_ref"]
            ):
                raise RALValidationError(
                    "authority_grant_attestation_mismatch",
                    "grant attestation does not match the authority snapshot",
                )
            if payload["authorship_verification_status"] != "verified":
                raise RALValidationError(
                    "authority_authorship_unverified",
                    "canonical grants require independently verified authorship",
                )
            if authority["status"] != "active":
                raise RALValidationError(
                    "authority_grant_inactive", "grant snapshot is not active"
                )
            authority_id = authority["authority_id"]
            previous = grants.get(authority_id)
            if previous is not None and previous.authority_digest != digest:
                raise RALValidationError(
                    "authority_grant_conflict",
                    "authority ID has conflicting canonical grant content",
                )
            if previous is None:
                grants[authority_id] = _AuthorityGrant(
                    authority=authority,
                    authority_digest=digest,
                    grant_event_id=event["event_id"],
                )
            continue
        if event_type != "authority.revoked":
            continue
        expected_fields = {
            "authority_id",
            "authority_digest",
            "authority_grant_event_id",
            "revocation",
        }
        if set(payload) != expected_fields:
            raise RALValidationError(
                "authority_revocation_invalid", "revocation payload fields differ"
            )
        authority_id = payload["authority_id"]
        grant = grants.get(authority_id)
        if grant is None:
            raise RALValidationError(
                "authority_grant_missing", "revocation has no prior grant"
            )
        if (
            payload["authority_digest"] != grant.authority_digest
            or payload["authority_grant_event_id"] != grant.grant_event_id
        ):
            raise RALValidationError(
                "authority_revocation_grant_mismatch",
                "revocation does not bind the canonical grant",
            )
        revocation = payload["revocation"]
        if (
            not isinstance(revocation, Mapping)
            or revocation.get("authority_id") != authority_id
        ):
            raise RALValidationError(
                "authority_revocation_invalid", "revocation authority differs"
            )
        revoked = dict(grant.authority)
        revoked["status"] = "revoked"
        revoked["revoked_by_event"] = event["event_id"]
        grants[authority_id] = _AuthorityGrant(
            authority=revoked,
            authority_digest=grant.authority_digest,
            grant_event_id=grant.grant_event_id,
        )
    return grants


def project_authorities(
    events: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    grants = _project_authority_grants(events)
    return tuple(grants[key].authority for key in sorted(grants))
