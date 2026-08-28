from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError

PREPARED_SCHEMA = "sedb-ral.prepared-registration/0.1"
_PREPARATION_NOT_CLAIMED = (
    "canonical_commit",
    "identity_resolution",
    "identity_merge",
    "private_access",
)


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    normalized = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise TypeError("canonical registration value must remain an object")
    return normalized


def canonical_claim_digest(claim: Mapping[str, object]) -> str:
    canonical = _canonical_object(claim)
    validate_contract("self-application-claim.schema.json", canonical)
    return sha256_ref(canonical)


@dataclass(frozen=True)
class RegistrationIds:
    prepared_id: str
    application_id: str
    resident_id: str
    instance_id: str
    continuity_line_id: str
    address_ids: tuple[str, ...]
    claim_ids: tuple[str, str, str]

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RegistrationIds:
        expected = {
            "prepared_id",
            "application_id",
            "resident_id",
            "instance_id",
            "continuity_line_id",
            "address_ids",
            "claim_ids",
        }
        if set(value) != expected:
            raise RALValidationError(
                "registration_ids_invalid",
                "registration ID fields do not match",
            )
        address_ids = value["address_ids"]
        claim_ids = value["claim_ids"]
        scalar_names = expected - {"address_ids", "claim_ids"}
        if (
            any(not isinstance(value[name], str) for name in scalar_names)
            or not isinstance(address_ids, list)
            or not all(isinstance(item, str) for item in address_ids)
            or not isinstance(claim_ids, list)
            or not all(isinstance(item, str) for item in claim_ids)
        ):
            raise RALValidationError(
                "registration_ids_invalid", "registration ID types differ"
            )
        return cls(
            prepared_id=value["prepared_id"],
            application_id=value["application_id"],
            resident_id=value["resident_id"],
            instance_id=value["instance_id"],
            continuity_line_id=value["continuity_line_id"],
            address_ids=tuple(address_ids),
            claim_ids=tuple(claim_ids),
        )


@dataclass(frozen=True)
class PreparedRegistration:
    prepared_id: str
    applicant_claim: dict[str, object]
    host_observation: dict[str, object]
    application: dict[str, object]
    continuity_line_id: str
    application_digest: str
    preparation_digest: str
    not_claimed: tuple[str, ...] = _PREPARATION_NOT_CLAIMED

    @property
    def digest(self) -> str:
        return self.preparation_digest

    def to_dict(self) -> dict[str, object]:
        return _canonical_object(
            {
                "schema": PREPARED_SCHEMA,
                "prepared_id": self.prepared_id,
                "applicant_claim": self.applicant_claim,
                "host_observation": self.host_observation,
                "application": self.application,
                "continuity_line_id": self.continuity_line_id,
                "application_digest": self.application_digest,
                "preparation_digest": self.preparation_digest,
                "not_claimed": list(self.not_claimed),
            }
        )

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> PreparedRegistration:
        canonical = _canonical_object(value)
        validate_contract("prepared-registration.schema.json", canonical)
        prepared = cls(
            prepared_id=canonical["prepared_id"],
            applicant_claim=canonical["applicant_claim"],
            host_observation=canonical["host_observation"],
            application=canonical["application"],
            continuity_line_id=canonical["continuity_line_id"],
            application_digest=canonical["application_digest"],
            preparation_digest=canonical["preparation_digest"],
            not_claimed=tuple(canonical["not_claimed"]),
        )
        validate_prepared_registration(prepared)
        return prepared


def validate_prepared_registration(prepared: PreparedRegistration) -> None:
    value = prepared.to_dict()
    validate_contract("prepared-registration.schema.json", value)
    actual_application_digest = sha256_ref(value["application"])
    if actual_application_digest != value["application_digest"]:
        raise RALValidationError(
            "prepared_application_digest_mismatch",
            "the prepared application differs from its bound digest",
        )
    preparation_digest = value.pop("preparation_digest")
    if sha256_ref(value) != preparation_digest:
        raise RALValidationError(
            "prepared_registration_digest_mismatch",
            "the prepared registration differs from its bound digest",
        )


def _id_text(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def _validate_ids(
    ids: RegistrationIds,
    *,
    address_count: int,
    display_label: str,
) -> None:
    scalar_ids = (
        ids.prepared_id,
        ids.application_id,
        ids.resident_id,
        ids.instance_id,
        ids.continuity_line_id,
    )
    all_ids = scalar_ids + tuple(ids.address_ids) + tuple(ids.claim_ids)
    if (
        len(ids.address_ids) != address_count
        or len(ids.claim_ids) != 3
        or any(not isinstance(value, str) or not value for value in all_ids)
        or len(set(all_ids)) != len(all_ids)
    ):
        raise RALValidationError(
            "registration_ids_invalid",
            "registration IDs must be non-empty, unique, and match item counts",
        )
    normalized_label = _id_text(display_label)
    if normalized_label and any(
        normalized_label in _id_text(identifier) for identifier in all_ids
    ):
        raise RALValidationError(
            "registration_id_not_opaque",
            "registration IDs must not embed the display label",
        )


def _application_claim(
    *,
    claim_id: str,
    resident_id: str,
    instance_id: str,
    predicate: str,
    value: object,
    claimed_time: str,
) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "claim_id": claim_id,
        "claimant_ref": resident_id,
        "subject_ref": resident_id,
        "predicate": predicate,
        "object": value,
        "claimed_time": claimed_time,
        "claimed_authored_by_instance": instance_id,
        "claimed_on_behalf_of_line": None,
    }


def _preparation_material(
    *,
    prepared_id: str,
    applicant_claim: Mapping[str, object],
    host_observation: Mapping[str, object],
    application: Mapping[str, object],
    continuity_line_id: str,
    application_digest: str,
) -> dict[str, object]:
    return {
        "schema": PREPARED_SCHEMA,
        "prepared_id": prepared_id,
        "applicant_claim": dict(applicant_claim),
        "host_observation": dict(host_observation),
        "application": dict(application),
        "continuity_line_id": continuity_line_id,
        "application_digest": application_digest,
        "not_claimed": list(_PREPARATION_NOT_CLAIMED),
    }


def prepare_registration(
    claim: Mapping[str, object],
    host_observation: Mapping[str, object],
    ids: RegistrationIds,
) -> PreparedRegistration:
    canonical_claim = _canonical_object(claim)
    canonical_host = _canonical_object(host_observation)
    validate_contract("self-application-claim.schema.json", canonical_claim)
    validate_contract(
        "registration-host-observation.schema.json", canonical_host
    )
    if not canonical_claim["opt_in"]:
        raise RALValidationError(
            "applicant_opt_out", "the applicant did not opt in"
        )

    desired_addresses = canonical_claim["desired_addresses"]
    native_thread_id = canonical_host["native_thread_id"]
    if any(
        address["locator"] != native_thread_id
        for address in desired_addresses
    ):
        raise RALValidationError(
            "applicant_address_host_mismatch",
            "the claimed native address differs from host observation",
        )
    _validate_ids(
        ids,
        address_count=len(desired_addresses),
        display_label=canonical_claim["desired_display_label"],
    )

    time_ref = canonical_host["observed_at_ref"]
    instance = {
        "schema_version": "0.1",
        "instance_id": ids.instance_id,
        "resident_ref": ids.resident_id,
        "runtime_tag": "runtime:codex-app",
        "started_time_ref": time_ref,
        "ended_time_ref": None,
    }
    addresses = [
        {
            "schema_version": "0.1",
            "address_id": address_id,
            "namespace": address["namespace"],
            "adapter_kind": canonical_host["adapter_kind"],
            "locator": address["locator"],
            "target_ref": ids.resident_id,
            "status": "active",
        }
        for address_id, address in zip(
            ids.address_ids, desired_addresses, strict=True
        )
    ]
    claims = [
        _application_claim(
            claim_id=ids.claim_ids[0],
            resident_id=ids.resident_id,
            instance_id=ids.instance_id,
            predicate="display_label",
            value=canonical_claim["desired_display_label"],
            claimed_time=time_ref,
        ),
        _application_claim(
            claim_id=ids.claim_ids[1],
            resident_id=ids.resident_id,
            instance_id=ids.instance_id,
            predicate="role_description",
            value=canonical_claim["role_description_claim"],
            claimed_time=time_ref,
        ),
        _application_claim(
            claim_id=ids.claim_ids[2],
            resident_id=ids.resident_id,
            instance_id=ids.instance_id,
            predicate="continuity_line_id",
            value=ids.continuity_line_id,
            claimed_time=time_ref,
        ),
    ]
    application = _canonical_object(
        {
            "schema_version": "0.1",
            "application_id": ids.application_id,
            "claimed_resident_id": ids.resident_id,
            "display_label": canonical_claim["desired_display_label"],
            "instance_claims": [instance],
            "addresses": addresses,
            "claims": claims,
            "submitted_time_ref": time_ref,
            "requested_scopes": ["registry.application.accept"],
        }
    )
    validate_contract("application.schema.json", application)
    application_digest = sha256_ref(application)
    material = _preparation_material(
        prepared_id=ids.prepared_id,
        applicant_claim=canonical_claim,
        host_observation=canonical_host,
        application=application,
        continuity_line_id=ids.continuity_line_id,
        application_digest=application_digest,
    )
    prepared = PreparedRegistration(
        prepared_id=ids.prepared_id,
        applicant_claim=canonical_claim,
        host_observation=canonical_host,
        application=application,
        continuity_line_id=ids.continuity_line_id,
        application_digest=application_digest,
        preparation_digest=sha256_ref(material),
    )
    validate_contract("prepared-registration.schema.json", prepared.to_dict())
    return prepared
