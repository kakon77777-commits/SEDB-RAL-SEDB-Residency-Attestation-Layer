from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .registration import (
    PreparedRegistration,
    RegistrationIds,
    canonical_claim_digest,
    prepare_registration,
)
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_models import (
    ApplicantItemEvidence,
    RegistrationWavePreparedCandidate,
    WaveHostObservation,
)

IdsFactory = Callable[[], RegistrationIds]


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
) -> None:
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
    ):
        raise RALValidationError(
            "applicant_item_binding_mismatch",
            "claim, item, and host observation bindings differ",
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
    for field in (
        "applicant_item_evidence_ref",
        "applicant_item_evidence_digest",
        "canonical_claim_digest",
        "observation_digest",
    ):
        value.pop(field)
    validate_contract("registration-host-observation.schema.json", value)
    return value


def verify_prepared_candidate_bindings(
    candidate: Mapping[str, object] | RegistrationWavePreparedCandidate,
    *,
    claim: Mapping[str, object],
    item: Mapping[str, object] | ApplicantItemEvidence,
    host_v02: Mapping[str, object] | WaveHostObservation,
    compatibility_host_v01: Mapping[str, object],
    prepared: PreparedRegistration | None,
) -> None:
    parsed_candidate = (
        candidate
        if isinstance(candidate, RegistrationWavePreparedCandidate)
        else RegistrationWavePreparedCandidate.from_dict(candidate)
    )
    parsed_item = (
        item if isinstance(item, ApplicantItemEvidence) else ApplicantItemEvidence.from_dict(item)
    )
    parsed_host = (
        host_v02
        if isinstance(host_v02, WaveHostObservation)
        else WaveHostObservation.from_dict(host_v02)
    )
    validate_contract("registration-host-observation.schema.json", compatibility_host_v01)
    value = parsed_candidate.to_dict()
    claim_digest = canonical_claim_digest(claim)
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
        "canonical_locator": claim["desired_addresses"][0]["locator"],
    }
    if any(value[name] != expected_value for name, expected_value in expected.items()):
        raise RALValidationError(
            "wave_candidate_evidence_mismatch",
            "prepared candidate binds different source evidence",
        )
    if prepared is None:
        raise RALValidationError(
            "wave_candidate_evidence_unavailable",
            "prepared registration evidence is unavailable",
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


def prepare_wave_candidate(
    context: SyntheticWaveExecutionContext,
    claim: Mapping[str, object],
    item: Mapping[str, object] | ApplicantItemEvidence | None,
    host_v02: Mapping[str, object] | WaveHostObservation,
    ids_factory: IdsFactory,
) -> RegistrationWavePreparedCandidate:
    context.verify_before_io("prepare", context.target_root)
    canonical_claim = _canonical_object(claim)
    claim_digest = canonical_claim_digest(canonical_claim)
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
    verify_applicant_item_evidence(canonical_claim, item, host_v02)
    if item is None:
        raise AssertionError("unreachable applicant item branch")
    parsed_item = (
        item if isinstance(item, ApplicantItemEvidence) else ApplicantItemEvidence.from_dict(item)
    )
    parsed_host = (
        host_v02
        if isinstance(host_v02, WaveHostObservation)
        else WaveHostObservation.from_dict(host_v02)
    )
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
    verify_prepared_candidate_bindings(
        candidate,
        claim=canonical_claim,
        item=parsed_item,
        host_v02=parsed_host,
        compatibility_host_v01=compatibility,
        prepared=prepared,
    )
    return candidate


def validate_exact_three_candidates(
    candidates: Sequence[
        Mapping[str, object] | RegistrationWavePreparedCandidate
    ],
) -> tuple[RegistrationWavePreparedCandidate, ...]:
    parsed = tuple(
        value
        if isinstance(value, RegistrationWavePreparedCandidate)
        else RegistrationWavePreparedCandidate.from_dict(value)
        for value in candidates
    )
    if len(parsed) != 3:
        raise RALValidationError(
            "wave_exact_three_required", "Wave 1 requires exactly three candidates"
        )
    for field in (
        "candidate_id",
        "candidate_digest",
        "canonical_claim_digest",
        "item_evidence_digest",
        "host_v02_digest",
        "application_digest",
        "canonical_locator",
    ):
        if len({getattr(value, field) for value in parsed}) != 3:
            raise RALValidationError(
                "wave_exact_three_required",
                f"three candidates must have distinct {field}",
            )
    return parsed
