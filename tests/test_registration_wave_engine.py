from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_registration_wave_authority import (
    PRINCIPAL_REF,
    current_status,
    execution_artifact,
    execution_intent,
    principal_host,
    raw_principal_item,
    time_evidence,
)
from test_registration_wave_plan import candidates, checkpoint
from test_registration_wave_policy import (
    acl_observation,
    activation_bundle,
    install_active_dormant,
    policy_time,
    wave_context,
)
from test_registration_wave_policy import (
    published_storage as policy_published_storage,
)

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.ledger import read_verified_events
from sedb_ral.registration_wave_authority import (
    verify_slot_execution_authorization,
)
from sedb_ral.registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from sedb_ral.registration_wave_engine import plan_wave_slot, simulate_wave_slot
from sedb_ral.registration_wave_models import SyntheticWaveSlotExecutionResult
from sedb_ral.registration_wave_plan import (
    build_slot_request,
    verify_wave_receipt_prefix,
)
from sedb_ral.registration_wave_policy import activate_wave_policy
from sedb_ral.registration_wave_store import RegistrationWaveStore

CTCL = json.loads(
    (Path(__file__).parents[1] / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)
VERIFIED_ATTESTATIONS = frozenset({"attestation:synthetic-principal"})


@pytest.fixture
def published_storage(tmp_path):
    return policy_published_storage.__wrapped__(tmp_path)


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def engine_context(tmp_path: Path, journal=None):
    fixture_root = tmp_path / "engine-fixture"
    fixture_root.mkdir(parents=True)
    marker = {
        "schema": "sedb-ral.synthetic-wave-fixture-marker/0.1",
        "fixture_marker_ref": "fixture:wave-engine",
        "not_claimed": ["production_root", "real_applicant", "private_access"],
    }
    (fixture_root / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(marker))
    return SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=fixture_root,
        target_root=fixture_root / "execution",
        fixture_marker_ref=str(marker["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(marker),
        forbidden_roots=(),
        journal=journal or WaveEffectJournal(),
    )


def application_authority(candidate):
    return {
        "schema_version": "0.1",
        "authority_id": "authority:synthetic-principal",
        "principal_ref": PRINCIPAL_REF,
        "subject_kind": "application_digest",
        "subject_ref": candidate.application_digest,
        "scopes": ["registry.application.accept"],
        "status": "active",
        "issued_time_ref": "ctcl:instant:synthetic-authority",
        "revoked_by_event": None,
        "authorship_attestation_ref": "attestation:synthetic-principal",
    }


def setup_active_wave(tmp_path, storage):
    install_active_dormant(storage)
    selected_plan, selected_policy, approvals, activation_request, activation_authority = (
        activation_bundle(tmp_path / "activation", storage)
    )
    policy_context = wave_context(tmp_path, storage)
    activate_wave_policy(
        policy_context,
        storage,
        activation_request,
        approvals,
        activation_authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )
    return selected_plan, selected_policy, approvals, policy_context


def setup_slot_one(tmp_path, storage):
    selected_plan, selected_policy, approvals, policy_context = setup_active_wave(
        tmp_path, storage
    )
    selected_candidate = candidates(tmp_path / "slot-candidates")[0]
    prefix = verify_wave_receipt_prefix(selected_plan, ())
    request = build_slot_request(
        selected_plan,
        1,
        prefix,
        {"expected_ledger_head": None, "cli_token": "GENESIS", "ledger_event_count": 0},
    )
    status_view = current_status(selected_plan)
    intent = execution_intent(selected_plan, request, approvals[0])
    raw = raw_principal_item(
        intent, item_ref="user-item:slot-1", turn_id="turn:slot-1"
    )
    host = principal_host(raw)
    authorization = verify_slot_execution_authorization(
        execution_artifact(selected_plan, request, approvals[0], raw, host),
        selected_plan,
        request,
        approvals[0],
        selected_policy,
        checkpoint(),
        status_view,
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )
    return (
        selected_plan,
        selected_policy,
        approvals,
        policy_context,
        selected_candidate,
        request,
        authorization,
    )


def store_for_engine(context):
    store_context = SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=context.fixture_root,
        target_root=context.target_root / "store",
        fixture_marker_ref=context.fixture_marker_ref,
        fixture_marker_digest=context.fixture_marker_digest,
        forbidden_roots=(),
        journal=context.journal,
    )
    return RegistrationWaveStore(store_context, store_context.target_root, digest("wave"))


def test_simulate_slot_one_commits_exactly_one_candidate_and_stores_result(
    tmp_path, published_storage
):
    (
        selected_plan,
        _selected_policy,
        _approvals,
        policy_context,
        candidate,
        request,
        authorization,
    ) = setup_slot_one(tmp_path, published_storage)
    journal = WaveEffectJournal()
    context = engine_context(tmp_path, journal)
    context.target_root.mkdir()
    store = store_for_engine(context)
    ledger_root = context.target_root / "ledger"
    planned = plan_wave_slot(
        context,
        candidate=candidate,
        wave_plan=selected_plan,
        slot_request=request,
        execution_authorization=authorization,
        policy_context=policy_context,
        policy_storage=published_storage,
        policy_time=policy_time(),
        application_authority=application_authority(candidate),
        verified_attestation_refs=VERIFIED_ATTESTATIONS,
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging",
    )

    result = simulate_wave_slot(context, planned, store)

    assert isinstance(result, SyntheticWaveSlotExecutionResult)
    assert result.slot_index == 1
    assert result.execution_scope == "synthetic"
    assert result.production_wave_run == "NOT_RUN"
    assert result.live_limen_b6a == "NOT_RUN"
    assert len(read_verified_events(ledger_root, result.post_head)) == 4
    assert store.verify()["record_count"] == 1
    assert journal.synthetic_ledger_writes == 4
    assert journal.synthetic_receipt_writes == 1


def test_plain_candidate_cannot_plan_or_mutate_ledger(tmp_path, published_storage):
    selected_plan, _, _, policy_context, candidate, request, authorization = (
        setup_slot_one(tmp_path, published_storage)
    )
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    ledger_root = context.target_root / "ledger"

    with pytest.raises(Exception, match="verified_candidate_required"):
        plan_wave_slot(
            context,
            candidate=candidate.candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=application_authority(candidate),
            verified_attestation_refs=VERIFIED_ATTESTATIONS,
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=context.target_root / "staging",
        )

    assert not ledger_root.exists()


def test_candidate_request_mismatch_refuses_before_ledger_write(
    tmp_path, published_storage
):
    selected_plan, _, _, policy_context, _, request, authorization = setup_slot_one(
        tmp_path, published_storage
    )
    different_candidate = candidates(tmp_path / "different")[1]
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    ledger_root = context.target_root / "ledger"

    with pytest.raises(Exception, match="wave_slot_candidate_mismatch"):
        plan_wave_slot(
            context,
            candidate=different_candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=application_authority(different_candidate),
            verified_attestation_refs=VERIFIED_ATTESTATIONS,
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=context.target_root / "staging",
        )

    assert not ledger_root.exists()


def test_simulate_retry_returns_same_result_without_duplicate_events(
    tmp_path, published_storage
):
    selected_plan, _, _, policy_context, candidate, request, authorization = (
        setup_slot_one(tmp_path, published_storage)
    )
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context)
    ledger_root = context.target_root / "ledger"
    planned = plan_wave_slot(
        context,
        candidate=candidate,
        wave_plan=selected_plan,
        slot_request=request,
        execution_authorization=authorization,
        policy_context=policy_context,
        policy_storage=published_storage,
        policy_time=policy_time(),
        application_authority=application_authority(candidate),
        verified_attestation_refs=VERIFIED_ATTESTATIONS,
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging",
    )

    first = simulate_wave_slot(context, planned, store)
    second = simulate_wave_slot(context, planned, store)

    assert second.to_dict() == first.to_dict()
    assert len(read_verified_events(ledger_root, second.post_head)) == 4
