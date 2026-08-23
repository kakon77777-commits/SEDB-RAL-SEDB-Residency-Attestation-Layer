from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass

from .authority import authority_matches_subject, validate_authority
from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract


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


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    normalized = loads_strict(canonical_bytes(value).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise TypeError("canonical application must remain an object")
    return normalized


def application_digest(value: Mapping[str, object]) -> str:
    return sha256_ref(_canonical_object(value))


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
    digest = application_digest(application)
    resident_id = application["claimed_resident_id"]
    requested_scopes = set(application["requested_scopes"])

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
