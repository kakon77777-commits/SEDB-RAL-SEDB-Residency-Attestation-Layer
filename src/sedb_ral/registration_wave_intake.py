from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .registration import (
    PreparedRegistration,
    RegistrationIds,
    canonical_claim_digest,
    prepare_registration,
    validate_prepared_registration,
)
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_models import (
    ApplicantItemEvidence,
    RegistrationWavePreparedCandidate,
    WaveHostObservation,
    verify_ref_digest_registry,
)

IdsFactory = Callable[[], RegistrationIds]
_ITEM_CAPABILITY_TOKEN = object()
_CANDIDATE_CAPABILITY_TOKEN = object()


@dataclass(frozen=True)
class RawApplicantItemSnapshot:
    provider: str
    adapter_kind: str
    native_thread_id: str
    native_turn_id: str
    source_item_role: str
    source_item_kind: str
    source_item_status: str
    source_item_parent_thread_id: str
    source_item_parent_turn_id: str
    applicant_item_ref: str
    content_bytes: bytes = field(repr=False)

    def evidence_material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.raw-applicant-item-snapshot/0.1",
            "provider": self.provider,
            "adapter_kind": self.adapter_kind,
            "native_thread_id": self.native_thread_id,
            "native_turn_id": self.native_turn_id,
            "source_item_role": self.source_item_role,
            "source_item_kind": self.source_item_kind,
            "source_item_status": self.source_item_status,
            "source_item_parent_thread_id": self.source_item_parent_thread_id,
            "source_item_parent_turn_id": self.source_item_parent_turn_id,
            "applicant_item_ref": self.applicant_item_ref,
            "content_sha256": hashlib.sha256(self.content_bytes).hexdigest(),
        }

    @property
    def evidence_digest(self) -> str:
        return sha256_ref(self.evidence_material())


@dataclass(frozen=True)
class VerifiedApplicantItemEvidence:
    item: ApplicantItemEvidence
    host: WaveHostObservation
    raw_item: RawApplicantItemSnapshot = field(repr=False)
    claim_digest: str
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _ITEM_CAPABILITY_TOKEN:
            raise RALValidationError(
                "verified_item_capability_invalid",
                "verified item capability was not issued by the verifier",
            )

    def verify(self) -> None:
        material = {
            "claim_digest": self.claim_digest,
            "item_evidence_digest": self.item.digest,
            "host_observation_digest": self.host.digest,
            "raw_item_evidence_digest": self.raw_item.evidence_digest,
        }
        if sha256_ref(material) != self.verification_digest:
            raise RALValidationError(
                "verified_item_capability_invalid",
                "verified item capability digest differs",
            )


@dataclass(frozen=True)
class VerifiedPreparedCandidate:
    candidate: RegistrationWavePreparedCandidate
    verified_item: VerifiedApplicantItemEvidence
    compatibility_host_v01: dict[str, object]
    prepared: PreparedRegistration
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _CANDIDATE_CAPABILITY_TOKEN:
            raise RALValidationError(
                "verified_candidate_required",
                "prepared candidate capability was not issued by the verifier",
            )

    def __getattr__(self, name: str) -> object:
        return getattr(self.candidate, name)

    def to_dict(self) -> dict[str, object]:
        return self.candidate.to_dict()

    @property
    def digest(self) -> str:
        return self.candidate.digest

    def verify(self) -> None:
        self.verified_item.verify()
        validate_prepared_registration(self.prepared)
        material = {
            "candidate_digest": self.candidate.digest,
            "verified_item_digest": self.verified_item.verification_digest,
            "compatibility_host_v01_digest": sha256_ref(
                self.compatibility_host_v01
            ),
            "prepared_registration_digest": self.prepared.digest,
        }
        if sha256_ref(material) != self.verification_digest:
            raise RALValidationError(
                "verified_candidate_required",
                "verified candidate capability digest differs",
            )


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("wave intake value must remain an object")
    return canonical


def _claim_ref(claim_digest: str) -> str:
    return f"self-application-claim:{claim_digest.rsplit(':', 1)[-1]}"


def _compatibility_host_ref(host: Mapping[str, object]) -> str:
    return f"registration-host-observation-v0.1:{host['observation_id']}"


def _candidate_id(
    *,
    claim_digest: str,
    item_digest: str,
    host_digest: str,
    prepared_digest: str,
) -> str:
    seed = sha256_ref(
        {
            "claim_digest": claim_digest,
            "item_digest": item_digest,
            "host_digest": host_digest,
            "prepared_digest": prepared_digest,
        }
    )
    return f"candidate:{seed.rsplit(':', 1)[-1][:24]}"


def verify_applicant_item_evidence(
    claim: Mapping[str, object],
    item: Mapping[str, object] | ApplicantItemEvidence | None,
    host: Mapping[str, object] | WaveHostObservation,
    raw_item: RawApplicantItemSnapshot,
) -> VerifiedApplicantItemEvidence:
    if item is None:
        raise RALValidationError(
            "applicant_output_unavailable",
            "no completed applicant output item is available",
        )
    parsed_item = (
        item if isinstance(item, ApplicantItemEvidence) else ApplicantItemEvidence.from_dict(item)
    )
    parsed_host = (
        host if isinstance(host, WaveHostObservation) else WaveHostObservation.from_dict(host)
    )
    item_value = parsed_item.to_dict()
    host_value = parsed_host.to_dict()
    claim_digest = canonical_claim_digest(claim)
    try:
        raw_claim = loads_strict(raw_item.content_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise RALValidationError(
            "applicant_raw_item_content_invalid",
            "raw applicant item content is not strict UTF-8 JSON",
        ) from error
    if (
        not isinstance(raw_claim, dict)
        or canonical_bytes(raw_claim) != raw_item.content_bytes
        or raw_claim != _canonical_object(claim)
    ):
        raise RALValidationError(
            "applicant_raw_item_content_invalid",
            "raw applicant item content differs from the canonical claim",
        )
    if (
        host_value["provider"] != item_value["provider"]
        or host_value["adapter_kind"] != item_value["adapter_kind"]
        or host_value["native_thread_id"] != item_value["native_thread_id"]
        or host_value["native_turn_id"] != item_value["native_turn_id"]
        or host_value["applicant_item_ref"] != item_value["applicant_item_ref"]
        or host_value["applicant_item_evidence_ref"]
        != item_value["item_evidence_id"]
        or host_value["applicant_item_evidence_digest"] != parsed_item.digest
        or host_value["canonical_claim_digest"] != claim_digest
        or item_value["canonical_claim_digest"] != claim_digest
        or raw_item.provider != item_value["provider"]
        or raw_item.adapter_kind != item_value["adapter_kind"]
        or raw_item.native_thread_id != item_value["native_thread_id"]
        or raw_item.native_turn_id != item_value["native_turn_id"]
        or raw_item.source_item_role != item_value["source_item_role"]
        or raw_item.source_item_kind != item_value["source_item_kind"]
        or raw_item.source_item_status != item_value["source_item_status"]
        or raw_item.source_item_parent_thread_id
        != item_value["source_item_parent_thread_id"]
        or raw_item.source_item_parent_turn_id
        != item_value["source_item_parent_turn_id"]
        or raw_item.applicant_item_ref != item_value["applicant_item_ref"]
    ):
        raise RALValidationError(
            "applicant_item_binding_mismatch",
            "claim, item, and host observation bindings differ",
        )
    if item_value["raw_item_evidence_digest"] != raw_item.evidence_digest:
        raise RALValidationError(
            "applicant_raw_item_digest_mismatch",
            "raw applicant item digest differs from retained bytes",
        )
    verification_material = {
        "claim_digest": claim_digest,
        "item_evidence_digest": parsed_item.digest,
        "host_observation_digest": parsed_host.digest,
        "raw_item_evidence_digest": raw_item.evidence_digest,
    }
    return VerifiedApplicantItemEvidence(
        item=parsed_item,
        host=parsed_host,
        raw_item=raw_item,
        claim_digest=claim_digest,
        verification_digest=sha256_ref(verification_material),
        _token=_ITEM_CAPABILITY_TOKEN,
    )


def compatibility_host_observation_v01(
    host_v02: Mapping[str, object] | WaveHostObservation,
) -> dict[str, object]:
    parsed = (
        host_v02
        if isinstance(host_v02, WaveHostObservation)
        else WaveHostObservation.from_dict(host_v02)
    )
    value = parsed.to_dict()
    value["schema"] = "sedb-ral.registration-host-observation/0.1"
    for field_name in (
        "applicant_item_evidence_ref",
        "applicant_item_evidence_digest",
        "canonical_claim_digest",
        "observation_digest",
    ):
        value.pop(field_name)
    validate_contract("registration-host-observation.schema.json", value)
    return value


def _validate_wave_claim_profile(claim: Mapping[str, object]) -> None:
    required_nonclaims = {
        "verified_identity",
        "registrar_authority",
        "private_access",
    }
    addresses = claim["desired_addresses"]
    if (
        claim["applicant_claim_only"] is not True
        or claim["relay_is_authorship"] is not False
        or len(addresses) != 1
        or addresses[0]["namespace"] != "codex_thread"
        or addresses[0]["identifier_kind"] != "codex_thread"
        or not required_nonclaims <= set(claim["not_claimed"])
    ):
        raise RALValidationError(
            "wave_claim_profile_invalid",
            "claim does not satisfy the Wave 1 public-only profile",
        )


def verify_prepared_candidate_bindings(
    candidate: Mapping[str, object] | RegistrationWavePreparedCandidate,
    *,
    verified_item: VerifiedApplicantItemEvidence,
    compatibility_host_v01: Mapping[str, object],
    prepared: PreparedRegistration,
) -> VerifiedPreparedCandidate:
    verified_item.verify()
    validate_prepared_registration(prepared)
    parsed_candidate = (
        candidate
        if isinstance(candidate, RegistrationWavePreparedCandidate)
        else RegistrationWavePreparedCandidate.from_dict(candidate)
    )
    parsed_item = verified_item.item
    parsed_host = verified_item.host
    validate_contract("registration-host-observation.schema.json", compatibility_host_v01)
    value = parsed_candidate.to_dict()
    claim_digest = verified_item.claim_digest
    expected = {
        "claim_ref": _claim_ref(claim_digest),
        "canonical_claim_digest": claim_digest,
        "item_evidence_ref": parsed_item.item_evidence_id,
        "item_evidence_digest": parsed_item.digest,
        "host_v02_ref": parsed_host.observation_id,
        "host_v02_digest": parsed_host.digest,
        "compatibility_host_v01_ref": _compatibility_host_ref(
            compatibility_host_v01
        ),
        "compatibility_host_v01_digest": sha256_ref(compatibility_host_v01),
        "canonical_locator": parsed_host.native_thread_id,
    }
    if any(value[name] != expected_value for name, expected_value in expected.items()):
        raise RALValidationError(
            "wave_candidate_evidence_mismatch",
            "prepared candidate binds different source evidence",
        )
    prepared_value = prepared.to_dict()
    prepared_expected = {
        "prepared_registration_ref": prepared.prepared_id,
        "prepared_registration_digest": prepared.digest,
        "application_ref": prepared_value["application"]["application_id"],
        "application_digest": prepared.application_digest,
    }
    if any(
        value[name] != expected_value
        for name, expected_value in prepared_expected.items()
    ):
        raise RALValidationError(
            "wave_candidate_evidence_mismatch",
            "prepared candidate binds different registration evidence",
        )
    expected_candidate_id = _candidate_id(
        claim_digest=claim_digest,
        item_digest=parsed_item.digest,
        host_digest=parsed_host.digest,
        prepared_digest=prepared.digest,
    )
    if value["candidate_id"] != expected_candidate_id:
        raise RALValidationError(
            "wave_candidate_evidence_mismatch",
            "candidate ID does not bind the evidence set",
        )
    verification_material = {
        "candidate_digest": parsed_candidate.digest,
        "verified_item_digest": verified_item.verification_digest,
        "compatibility_host_v01_digest": sha256_ref(compatibility_host_v01),
        "prepared_registration_digest": prepared.digest,
    }
    return VerifiedPreparedCandidate(
        candidate=parsed_candidate,
        verified_item=verified_item,
        compatibility_host_v01=_canonical_object(compatibility_host_v01),
        prepared=prepared,
        verification_digest=sha256_ref(verification_material),
        _token=_CANDIDATE_CAPABILITY_TOKEN,
    )


def prepare_wave_candidate(
    context: SyntheticWaveExecutionContext,
    claim: Mapping[str, object],
    item: Mapping[str, object] | ApplicantItemEvidence | None,
    host_v02: Mapping[str, object] | WaveHostObservation,
    raw_item: RawApplicantItemSnapshot,
    ids_factory: IdsFactory,
) -> VerifiedPreparedCandidate:
    context.verify_before_io("prepare", context.target_root)
    canonical_claim = _canonical_object(claim)
    claim_digest = canonical_claim_digest(canonical_claim)
    _validate_wave_claim_profile(canonical_claim)
    if (
        canonical_claim["existing_resident_claim"] is not None
        or canonical_claim["continuity_claim"] not in {"new", "uncertain"}
    ):
        raise RALValidationError(
            "continuity_evidence_required",
            "Wave 1 cannot continue or merge an existing resident",
        )
    if canonical_claim["opt_in"] is not True:
        raise RALValidationError("applicant_opt_out", "applicant did not opt in")
    verified_item = verify_applicant_item_evidence(
        canonical_claim, item, host_v02, raw_item
    )
    parsed_item = verified_item.item
    parsed_host = verified_item.host
    selected_ids = ids_factory()
    if not isinstance(selected_ids, RegistrationIds):
        raise RALValidationError(
            "registration_ids_invalid", "ID factory returned another type"
        )
    compatibility = compatibility_host_observation_v01(parsed_host)
    prepared = prepare_registration(canonical_claim, compatibility, selected_ids)
    material = {
        "schema": "sedb-ral.registration-wave-prepared-candidate/0.1",
        "candidate_id": _candidate_id(
            claim_digest=claim_digest,
            item_digest=parsed_item.digest,
            host_digest=parsed_host.digest,
            prepared_digest=prepared.digest,
        ),
        "claim_ref": _claim_ref(claim_digest),
        "canonical_claim_digest": claim_digest,
        "item_evidence_ref": parsed_item.item_evidence_id,
        "item_evidence_digest": parsed_item.digest,
        "host_v02_ref": parsed_host.observation_id,
        "host_v02_digest": parsed_host.digest,
        "compatibility_host_v01_ref": _compatibility_host_ref(compatibility),
        "compatibility_host_v01_digest": sha256_ref(compatibility),
        "prepared_registration_ref": prepared.prepared_id,
        "prepared_registration_digest": prepared.digest,
        "application_ref": prepared.application["application_id"],
        "application_digest": prepared.application_digest,
        "canonical_locator": canonical_claim["desired_addresses"][0]["locator"],
        "not_claimed": [
            "verified_identity",
            "canonical_commit",
            "private_access",
            "continuity_merge",
        ],
    }
    candidate = RegistrationWavePreparedCandidate.sealed(material)
    return verify_prepared_candidate_bindings(
        candidate,
        verified_item=verified_item,
        compatibility_host_v01=compatibility,
        prepared=prepared,
    )


def validate_candidate_identity_registry(
    candidates: Sequence[RegistrationWavePreparedCandidate],
) -> None:
    values = tuple(candidate.to_dict() for candidate in candidates)
    verify_ref_digest_registry(
        values,
        (
            ("candidate", "candidate_id", "candidate_digest"),
            ("claim", "claim_ref", "canonical_claim_digest"),
            ("item_evidence", "item_evidence_ref", "item_evidence_digest"),
            ("host_v02", "host_v02_ref", "host_v02_digest"),
            (
                "compatibility_host_v01",
                "compatibility_host_v01_ref",
                "compatibility_host_v01_digest",
            ),
            (
                "prepared_registration",
                "prepared_registration_ref",
                "prepared_registration_digest",
            ),
            ("application", "application_ref", "application_digest"),
        ),
        code="wave_candidate_identity_conflict",
    )
    locators = [candidate.canonical_locator for candidate in candidates]
    if len(set(locators)) != len(locators):
        raise RALValidationError(
            "wave_candidate_identity_conflict",
            "candidate locators must be distinct",
        )


def validate_exact_three_candidates(
    candidates: Sequence[VerifiedPreparedCandidate],
) -> tuple[VerifiedPreparedCandidate, ...]:
    if any(not isinstance(value, VerifiedPreparedCandidate) for value in candidates):
        raise RALValidationError(
            "verified_candidate_required",
            "plain self-sealed candidates are not verified capabilities",
        )
    parsed = tuple(candidates)
    if len(parsed) != 3:
        raise RALValidationError(
            "wave_exact_three_required", "Wave 1 requires exactly three candidates"
        )
    for value in parsed:
        value.verify()
    try:
        validate_candidate_identity_registry(tuple(value.candidate for value in parsed))
    except RALValidationError as error:
        raise RALValidationError(
            "wave_exact_three_required", "three candidate identities conflict"
        ) from error
    return parsed
