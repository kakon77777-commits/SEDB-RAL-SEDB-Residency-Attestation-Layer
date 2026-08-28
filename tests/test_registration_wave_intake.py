from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration import RegistrationIds, canonical_claim_digest
from sedb_ral.registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from sedb_ral.registration_wave_intake import (
    RawApplicantItemSnapshot,
    VerifiedPreparedCandidate,
    compatibility_host_observation_v01,
    prepare_wave_candidate,
    validate_candidate_identity_registry,
    validate_exact_three_candidates,
    verify_applicant_item_evidence,
    verify_prepared_candidate_bindings,
)
from sedb_ral.registration_wave_models import RegistrationWavePreparedCandidate

THREADS = (
    "10000000-0000-4000-8000-000000000001",
    "20000000-0000-4000-8000-000000000002",
    "30000000-0000-4000-8000-000000000003",
)


def seal(value: dict[str, object], field: str) -> dict[str, object]:
    result = copy.deepcopy(value)
    result.pop(field, None)
    result[field] = sha256_ref(result)
    return result


def claim(index: int = 1, **changes) -> dict[str, object]:
    value = {
        "schema": "sedb-ral.self-application-claim/0.1",
        "applicant_claim_only": True,
        "desired_display_label": f"Synthetic Seat {index}",
        "existing_resident_claim": None,
        "continuity_claim": "new",
        "desired_addresses": [
            {
                "namespace": "codex_thread",
                "identifier_kind": "codex_thread",
                "locator": THREADS[index - 1],
            }
        ],
        "role_description_claim": f"Synthetic role {index}",
        "dissent_or_limits": ["public registration only"],
        "opt_in": True,
        "relay_is_authorship": False,
        "not_claimed": [
            "verified_identity",
            "registrar_authority",
            "private_access",
        ],
    }
    value.update(changes)
    return value


def raw_item(
    index: int = 1, claim_value: dict[str, object] | None = None
) -> RawApplicantItemSnapshot:
    selected_claim = claim(index) if claim_value is None else claim_value
    return RawApplicantItemSnapshot(
        provider="openai",
        adapter_kind="codex_app_task_tool",
        native_thread_id=THREADS[index - 1],
        native_turn_id=f"turn:slot-{index}",
        source_item_role="assistant",
        source_item_kind="agentMessage",
        source_item_status="completed",
        source_item_parent_thread_id=THREADS[index - 1],
        source_item_parent_turn_id=f"turn:slot-{index}",
        applicant_item_ref=f"item:slot-{index}",
        content_bytes=canonical_bytes(selected_claim),
    )


def item(
    index: int = 1,
    *,
    claim_value: dict[str, object] | None = None,
    **changes,
) -> dict[str, object]:
    selected_claim = claim(index) if claim_value is None else claim_value
    value = {
        "schema": "sedb-ral.registration-applicant-item-evidence/0.1",
        "item_evidence_id": f"item-evidence:slot-{index}",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "native_thread_id": THREADS[index - 1],
        "native_turn_id": f"turn:slot-{index}",
        "source_item_role": "assistant",
        "source_item_kind": "agentMessage",
        "source_item_status": "completed",
        "source_item_parent_thread_id": THREADS[index - 1],
        "source_item_parent_turn_id": f"turn:slot-{index}",
        "applicant_item_ref": f"item:slot-{index}",
        "canonical_claim_digest": canonical_claim_digest(selected_claim),
        "raw_item_evidence_digest": raw_item(index, selected_claim).evidence_digest,
        "capture_status": "host_observed",
        "observed_origin": "host:codex-app",
        "observed_at_ref": f"ctcl:instant:slot-{index}",
        "unavailable_fields": [
            {
                "field": "native_session_id",
                "reason": "structurally_unavailable_from_codex_app_task_tool",
            }
        ],
        "not_claimed": ["verified_identity", "registrar_authority"],
    }
    value.update(changes)
    return seal(value, "item_evidence_digest")


def host(
    index: int = 1,
    *,
    claim_value: dict[str, object] | None = None,
    item_value: dict[str, object] | None = None,
    **changes,
) -> dict[str, object]:
    selected_claim = claim(index) if claim_value is None else claim_value
    evidence = (
        item(index, claim_value=selected_claim) if item_value is None else item_value
    )
    value = {
        "schema": "sedb-ral.registration-host-observation/0.2",
        "observation_id": f"observation:slot-{index}",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "identifier_kind": "codex_thread",
        "native_thread_id": THREADS[index - 1],
        "native_session_id": None,
        "native_turn_id": f"turn:slot-{index}",
        "unavailable_fields": evidence["unavailable_fields"],
        "observed_origin": "host:codex-app",
        "observed_at_ref": f"ctcl:instant:slot-{index}",
        "applicant_item_ref": f"item:slot-{index}",
        "applicant_item_evidence_ref": f"item-evidence:slot-{index}",
        "applicant_item_evidence_digest": evidence["item_evidence_digest"],
        "canonical_claim_digest": canonical_claim_digest(selected_claim),
        "not_claimed": ["pre_turn_output_enforcement", "verified_identity"],
    }
    value.update(changes)
    return seal(value, "observation_digest")


def ids(index: int = 1) -> RegistrationIds:
    return RegistrationIds(
        prepared_id=f"prepared:{index:08x}",
        application_id=f"application:{index + 10:08x}",
        resident_id=f"resident:{index + 20:08x}",
        instance_id=f"instance:{index + 30:08x}",
        continuity_line_id=f"line:{index + 40:08x}",
        address_ids=(f"address:{index + 50:08x}",),
        claim_ids=(
            f"claim:{index + 60:08x}",
            f"claim:{index + 70:08x}",
            f"claim:{index + 80:08x}",
        ),
    )


@dataclass
class CountingIdsFactory:
    value: RegistrationIds
    calls: int = 0

    def __call__(self) -> RegistrationIds:
        self.calls += 1
        return self.value


def context(tmp_path: Path) -> SyntheticWaveExecutionContext:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir(parents=True, exist_ok=True)
    marker = {
        "schema": "sedb-ral.synthetic-wave-fixture-marker/0.1",
        "fixture_marker_ref": "fixture:wave-intake",
        "not_claimed": ["production_root", "real_applicant", "private_access"],
    }
    (fixture_root / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(marker))
    return SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=fixture_root,
        target_root=fixture_root / "wave",
        fixture_marker_ref=str(marker["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(marker),
        forbidden_roots=(),
        journal=WaveEffectJournal(),
    )


@pytest.mark.parametrize(
    ("role", "kind", "status"),
    (
        ("user", "userMessage", "completed"),
        ("assistant", "codexDelegation", "completed"),
        ("assistant", "reasoning", "completed"),
        ("assistant", "toolCall", "completed"),
        ("assistant", "commandExecution", "completed"),
        ("assistant", "agentMessage", "inProgress"),
    ),
)
def test_non_agent_items_cannot_prepare_or_allocate_ids(
    tmp_path, role, kind, status
):
    factory = CountingIdsFactory(ids())
    changed = item(
        source_item_role=role,
        source_item_kind=kind,
        source_item_status=status,
    )

    with pytest.raises(RALValidationError, match="applicant_item_role_invalid"):
        prepare_wave_candidate(
            context(tmp_path), claim(), changed, host(), raw_item(), factory
        )

    assert factory.calls == 0


@pytest.mark.parametrize(
    "claim_change",
    (
        {"continuity_claim": "continue"},
        {"existing_resident_claim": "resident:old"},
        {"opt_in": False},
    ),
)
def test_continuity_or_opt_out_stops_before_id_assignment(tmp_path, claim_change):
    factory = CountingIdsFactory(ids())
    changed = claim(**claim_change)

    with pytest.raises(
        RALValidationError,
        match="continuity_evidence_required|applicant_opt_out",
    ):
        prepare_wave_candidate(
            context(tmp_path), changed, item(), host(), raw_item(), factory
        )

    assert factory.calls == 0


def test_missing_agent_message_stops_before_id_assignment(tmp_path):
    factory = CountingIdsFactory(ids())

    with pytest.raises(RALValidationError, match="applicant_output_unavailable"):
        verify_applicant_item_evidence(claim(), None, host(), raw_item())
    with pytest.raises(RALValidationError, match="applicant_output_unavailable"):
        prepare_wave_candidate(
            context(tmp_path), claim(), None, host(), raw_item(), factory
        )

    assert factory.calls == 0


def test_wave_claim_profile_requires_all_public_only_nonclaims_before_ids(tmp_path):
    selected_claim = claim(not_claimed=["verified_identity"])
    selected_raw = raw_item(claim_value=selected_claim)
    selected_item = item(claim_value=selected_claim)
    selected_host = host(claim_value=selected_claim, item_value=selected_item)
    factory = CountingIdsFactory(ids())

    with pytest.raises(RALValidationError, match="wave_claim_profile_invalid"):
        prepare_wave_candidate(
            context(tmp_path),
            selected_claim,
            selected_item,
            selected_host,
            selected_raw,
            factory,
        )

    assert factory.calls == 0


def test_resealed_fabricated_raw_item_digest_cannot_become_verified(tmp_path):
    selected_claim = claim()
    selected_raw = raw_item(claim_value=selected_claim)
    selected_item = item(claim_value=selected_claim)
    selected_item["raw_item_evidence_digest"] = sha256_ref({"fabricated": True})
    selected_item = seal(selected_item, "item_evidence_digest")
    selected_host = host(claim_value=selected_claim, item_value=selected_item)
    factory = CountingIdsFactory(ids())

    with pytest.raises(
        RALValidationError, match="applicant_raw_item_digest_mismatch"
    ):
        prepare_wave_candidate(
            context(tmp_path),
            selected_claim,
            selected_item,
            selected_host,
            selected_raw,
            factory,
        )

    assert factory.calls == 0


@pytest.mark.parametrize(
    "host_change",
    (
        {"applicant_item_ref": "item:other"},
        {"applicant_item_evidence_ref": "item-evidence:other"},
        {"applicant_item_evidence_digest": sha256_ref({"other": True})},
        {"canonical_claim_digest": sha256_ref({"other-claim": True})},
        {"native_turn_id": "turn:other"},
    ),
)
def test_swapped_host_item_or_claim_binding_stops_before_id_assignment(
    tmp_path, host_change
):
    factory = CountingIdsFactory(ids())
    changed_host = host(**host_change)

    with pytest.raises(RALValidationError, match="applicant_item_binding_mismatch"):
        prepare_wave_candidate(
            context(tmp_path), claim(), item(), changed_host, raw_item(), factory
        )

    assert factory.calls == 0


def test_valid_preparation_allocates_once_and_binds_durable_wrapper(tmp_path):
    selected_claim = claim()
    selected_item = item()
    selected_host = host()
    factory = CountingIdsFactory(ids())

    candidate = prepare_wave_candidate(
        context(tmp_path),
        selected_claim,
        selected_item,
        selected_host,
        raw_item(),
        factory,
    )
    compatibility = compatibility_host_observation_v01(selected_host)

    assert factory.calls == 1
    assert isinstance(candidate, VerifiedPreparedCandidate)
    assert candidate.canonical_claim_digest == canonical_claim_digest(selected_claim)
    assert candidate.item_evidence_digest == selected_item["item_evidence_digest"]
    assert candidate.host_v02_digest == selected_host["observation_digest"]
    assert candidate.compatibility_host_v01_digest == sha256_ref(compatibility)
    assert candidate.application_ref == ids().application_id
    assert candidate.canonical_locator == THREADS[0]
    assert (
        RegistrationWavePreparedCandidate.from_dict(candidate.to_dict())
        == candidate.candidate
    )


def test_restart_verifier_rejects_resealed_swapped_evidence(tmp_path):
    selected_claim = claim()
    selected_item = item()
    selected_host = host()
    candidate = prepare_wave_candidate(
        context(tmp_path),
        selected_claim,
        selected_item,
        selected_host,
        raw_item(),
        CountingIdsFactory(ids()),
    )
    changed = candidate.to_dict()
    changed["item_evidence_digest"] = sha256_ref({"swapped": True})
    changed = seal(changed, "candidate_digest")

    with pytest.raises(RALValidationError, match="wave_candidate_evidence_mismatch"):
        verify_prepared_candidate_bindings(
            RegistrationWavePreparedCandidate.from_dict(changed),
            verified_item=candidate.verified_item,
            compatibility_host_v01=candidate.compatibility_host_v01,
            prepared=candidate.prepared,
        )


def test_verified_candidate_revalidates_mutable_prepared_body(tmp_path):
    verified = prepare_wave_candidate(
        context(tmp_path),
        claim(),
        item(),
        host(),
        raw_item(),
        CountingIdsFactory(ids()),
    )
    verified.prepared.application["display_label"] = "Tampered"

    with pytest.raises(RALValidationError, match="prepared_application_digest_mismatch"):
        verified.verify()


def test_exact_three_candidates_preserve_order_and_reject_duplicate_locator(tmp_path):
    candidates = tuple(
        prepare_wave_candidate(
            context(tmp_path / f"slot-{index}"),
            claim(index),
            item(index),
            host(index),
            raw_item(index),
            CountingIdsFactory(ids(index)),
        )
        for index in (1, 2, 3)
    )

    assert validate_exact_three_candidates(candidates) == candidates

    with pytest.raises(RALValidationError, match="verified_candidate_required"):
        validate_exact_three_candidates(tuple(value.candidate for value in candidates))

    with pytest.raises(RALValidationError, match="wave_exact_three_required"):
        validate_exact_three_candidates((candidates[0], candidates[1], candidates[1]))


@pytest.mark.parametrize(
    "ref_field",
    (
        "candidate_id",
        "claim_ref",
        "item_evidence_ref",
        "host_v02_ref",
        "compatibility_host_v01_ref",
        "prepared_registration_ref",
        "application_ref",
    ),
)
def test_candidate_identity_registry_rejects_same_ref_with_different_digest(
    tmp_path, ref_field
):
    verified = tuple(
        prepare_wave_candidate(
            context(tmp_path / f"identity-{index}"),
            claim(index),
            item(index),
            host(index),
            raw_item(index),
            CountingIdsFactory(ids(index)),
        )
        for index in (1, 2, 3)
    )
    plain = [value.candidate for value in verified]
    changed = plain[2].to_dict()
    changed[ref_field] = plain[1].to_dict()[ref_field]
    plain[2] = RegistrationWavePreparedCandidate.from_dict(
        seal(changed, "candidate_digest")
    )

    with pytest.raises(RALValidationError, match="wave_candidate_identity_conflict"):
        validate_candidate_identity_registry(tuple(plain))


def test_canonical_claim_digest_validates_without_mutating_input():
    value = claim()
    before = copy.deepcopy(value)

    observed = canonical_claim_digest(value)

    assert observed == sha256_ref(value)
    assert value == before
