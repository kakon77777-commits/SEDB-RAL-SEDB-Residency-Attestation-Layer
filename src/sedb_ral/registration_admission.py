from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from .application import evaluate_application
from .canonical import sha256_ref
from .projection import RegistryProjection, continuity_line_for
from .registration import (
    PreparedRegistration,
    validate_prepared_registration,
)

_NOT_CLAIMED = ("canonical_commit", "private_access", "identity_merge")


@dataclass(frozen=True)
class RegistrationDecision:
    decision: str
    reason_codes: tuple[str, ...]
    prepared_digest: str
    application_digest: str
    authority_ref: str | None
    resident_id: str
    address_refs: tuple[str, ...]
    mutated: bool = False
    not_claimed: tuple[str, ...] = _NOT_CLAIMED

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.registration-decision/0.1",
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "prepared_digest": self.prepared_digest,
            "application_digest": self.application_digest,
            "authority_ref": self.authority_ref,
            "resident_id": self.resident_id,
            "address_refs": list(self.address_refs),
            "mutated": self.mutated,
            "not_claimed": list(self.not_claimed),
        }

    @property
    def digest(self) -> str:
        return sha256_ref(self._material())

    def to_dict(self) -> dict[str, object]:
        return {**self._material(), "digest": self.digest}

    def as_json(self) -> dict[str, object]:
        return self.to_dict()


def _decision(
    prepared: PreparedRegistration,
    decision: str,
    code: str,
    authority_ref: str | None = None,
) -> RegistrationDecision:
    application = prepared.application
    return RegistrationDecision(
        decision=decision,
        reason_codes=(code,),
        prepared_digest=prepared.digest,
        application_digest=prepared.application_digest,
        authority_ref=authority_ref,
        resident_id=str(application["claimed_resident_id"]),
        address_refs=tuple(
            str(address["address_id"])
            for address in application["addresses"]
        ),
    )


def _continuity_gate(
    prepared: PreparedRegistration,
    projection: RegistryProjection,
    authority_ref: str | None,
) -> RegistrationDecision | None:
    claim = prepared.applicant_claim
    resident_id = str(prepared.application["claimed_resident_id"])
    existing_ref = claim["existing_resident_claim"]
    continuity_claim = claim["continuity_claim"]
    if continuity_claim == "uncertain":
        return _decision(
            prepared, "defer", "continuity_uncertain", authority_ref
        )
    if continuity_claim == "new":
        if existing_ref is not None:
            return _decision(
                prepared,
                "defer",
                "continuity_claim_conflict",
                authority_ref,
            )
        if resident_id in projection.residents:
            return _decision(
                prepared, "reject", "resident_id_conflict", authority_ref
            )
        for other_id, resident in projection.residents.items():
            if resident.get("status") != "active":
                continue
            line_id = continuity_line_for(other_id, projection)
            if line_id == prepared.continuity_line_id:
                return _decision(
                    prepared,
                    "reject",
                    "continuity_line_conflict",
                    authority_ref,
                )
        return None

    if not isinstance(existing_ref, str) or existing_ref not in projection.residents:
        return _decision(
            prepared,
            "defer",
            "continuity_resident_missing",
            authority_ref,
        )
    resident = projection.residents[existing_ref]
    if resident.get("status") != "active":
        return _decision(
            prepared,
            "defer",
            "continuity_resident_inactive",
            authority_ref,
        )
    if resident_id != existing_ref:
        return _decision(
            prepared,
            "reject",
            "continuity_resident_mismatch",
            authority_ref,
        )
    line_id = continuity_line_for(existing_ref, projection)
    if line_id is None:
        return _decision(
            prepared,
            "defer",
            "continuity_line_missing",
            authority_ref,
        )
    if line_id != prepared.continuity_line_id:
        return _decision(
            prepared,
            "reject",
            "continuity_line_conflict",
            authority_ref,
        )
    return None


def _identifier_collision_gate(
    prepared: PreparedRegistration,
    projection: RegistryProjection,
    authority_ref: str | None,
) -> RegistrationDecision | None:
    application = prepared.application
    application_id = str(application["application_id"])
    if application_id in projection.applications:
        return _decision(
            prepared, "reject", "application_id_conflict", authority_ref
        )

    existing_instance_ids: set[str] = set()
    existing_address_ids: set[str] = set()
    existing_claim_ids = set(projection.claims)
    active_addresses: list[tuple[str, Mapping[str, object]]] = []
    for resident_id, resident in projection.residents.items():
        for instance in resident.get("instances", ()):
            existing_instance_ids.add(str(instance["instance_id"]))
        for address in resident.get("addresses", ()):
            existing_address_ids.add(str(address["address_id"]))
            if address.get("status") == "active":
                active_addresses.append((resident_id, address))
        for claim in resident.get("claims", ()):
            existing_claim_ids.add(str(claim["claim_id"]))

    if any(
        str(instance["instance_id"]) in existing_instance_ids
        for instance in application["instance_claims"]
    ):
        return _decision(
            prepared, "reject", "instance_id_conflict", authority_ref
        )
    if any(
        str(address["address_id"]) in existing_address_ids
        for address in application["addresses"]
    ):
        return _decision(
            prepared, "reject", "address_id_conflict", authority_ref
        )
    if any(
        str(claim["claim_id"]) in existing_claim_ids
        for claim in application["claims"]
    ):
        return _decision(
            prepared, "reject", "claim_id_conflict", authority_ref
        )

    candidate_resident_id = str(application["claimed_resident_id"])
    for candidate in application["addresses"]:
        for bound_resident_id, existing in active_addresses:
            if (
                existing.get("namespace") != candidate["namespace"]
                or existing.get("locator") != candidate["locator"]
            ):
                continue
            code = (
                "address_binding_duplicate"
                if bound_resident_id == candidate_resident_id
                else "address_binding_conflict"
            )
            return _decision(prepared, "reject", code, authority_ref)
    return None


def evaluate_prepared_registration(
    prepared: PreparedRegistration,
    authorities: Iterable[Mapping[str, object]],
    verified_attestation_refs: AbstractSet[str],
    projection: RegistryProjection,
) -> RegistrationDecision:
    validate_prepared_registration(prepared)
    exact_authorities = [
        authority
        for authority in authorities
        if authority.get("subject_kind") == "application_digest"
        and authority.get("subject_ref") == prepared.application_digest
    ]
    base = evaluate_application(
        prepared.application,
        exact_authorities,
        verified_attestation_refs=verified_attestation_refs,
    )
    if base.decision != "accept":
        return _decision(
            prepared,
            base.decision,
            base.reason_codes[0],
            base.authority_ref,
        )
    if projection.unapplied_event_ids:
        return _decision(
            prepared,
            "defer",
            "projection_unapplied_events",
            base.authority_ref,
        )
    continuity = _continuity_gate(prepared, projection, base.authority_ref)
    if continuity is not None:
        return continuity
    collision = _identifier_collision_gate(
        prepared, projection, base.authority_ref
    )
    if collision is not None:
        return collision
    return _decision(
        prepared, "accept", "authority_sufficient", base.authority_ref
    )
