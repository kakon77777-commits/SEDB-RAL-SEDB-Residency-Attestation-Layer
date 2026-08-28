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
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import read_verified_events
from sedb_ral.registration_wave_authority import (
    derive_verified_application_authority,
    verify_slot_execution_authorization,
)
from sedb_ral.registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from sedb_ral.registration_wave_engine import (
    plan_wave_slot,
    simulate_wave_slot,
    verify_synthetic_wave_result_prefix,
)
from sedb_ral.registration_wave_models import (
    SyntheticWaveSlotExecutionResult,
    WaveSlotRequest,
)
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
        "authority_id": (
            "authority:synthetic-principal:"
            f"{candidate.application_digest.rsplit(':', 1)[-1][:16]}"
        ),
        "principal_ref": PRINCIPAL_REF,
        "subject_kind": "application_digest",
        "subject_ref": candidate.application_digest,
        "scopes": ["registry.application.accept"],
        "status": "active",
        "issued_time_ref": "ctcl:instant:synthetic-authority",
        "revoked_by_event": None,
        "authorship_attestation_ref": "attestation:synthetic-principal",
    }


def verified_application_authority(candidate, execution_authorization, time=None):
    return derive_verified_application_authority(
        candidate.application_digest,
        execution_authorization,
        time or policy_time(),
    )


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


def store_for_engine(context, expected_wave_digest):
    store_context = SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=context.fixture_root,
        target_root=context.target_root / "store",
        fixture_marker_ref=context.fixture_marker_ref,
        fixture_marker_digest=context.fixture_marker_digest,
        forbidden_roots=(),
        journal=context.journal,
    )
    return RegistrationWaveStore(
        store_context, store_context.target_root, expected_wave_digest
    )


def synthetic_request(selected_plan, slot_index, result_prefix):
    slot = selected_plan.ordered_slots[slot_index - 1]
    predecessor = None if not result_prefix.results else result_prefix.results[-1]
    head = result_prefix.final_head
    return WaveSlotRequest.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-request/0.1",
            "request_id": f"slot-request:synthetic:{slot_index}",
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": slot["slot_id"],
            "slot_index": slot_index,
            "candidate_ref": slot["candidate_ref"],
            "candidate_digest": slot["candidate_digest"],
            "application_ref": slot["application_ref"],
            "application_digest": slot["application_digest"],
            "predecessor_receipt_ref": (
                None if predecessor is None else predecessor.result_id
            ),
            "predecessor_receipt_digest": (
                None if predecessor is None else predecessor.digest
            ),
            "expected_ledger_state": {
                "expected_ledger_head": head,
                "cli_token": "GENESIS" if head is None else head,
                "ledger_event_count": result_prefix.ledger_event_count,
            },
            "policy_ref": selected_plan.policy_ref,
            "policy_digest": selected_plan.policy_digest,
            "checkpoint_ref": selected_plan.checkpoint_ref,
            "checkpoint_digest": selected_plan.checkpoint_digest,
            "registry_generation_digest": selected_plan.registry_generation_digest,
            "registry_control_digest": selected_plan.registry_control_digest,
            "not_claimed": ["batch_execution", "rank", "authority"],
        }
    )


def verified_slot_authorization(
    selected_plan,
    selected_policy,
    approval,
    request,
    *,
    item_suffix,
):
    intent = execution_intent(selected_plan, request, approval)
    raw = raw_principal_item(
        intent,
        item_ref=f"user-item:{item_suffix}",
        turn_id=f"turn:{item_suffix}",
    )
    host = principal_host(raw)
    return verify_slot_execution_authorization(
        execution_artifact(selected_plan, request, approval, raw, host),
        selected_plan,
        request,
        approval,
        selected_policy,
        checkpoint(),
        current_status(
            selected_plan,
            request.expected_ledger_state["expected_ledger_head"],
        ),
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )


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
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    planned = plan_wave_slot(
        context,
        candidate=candidate,
        wave_plan=selected_plan,
        slot_request=request,
        execution_authorization=authorization,
        result_prefix=result_prefix,
        policy_context=policy_context,
        policy_storage=published_storage,
        policy_time=policy_time(),
        application_authority=verified_application_authority(
            candidate, authorization
        ),
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging",
    )

    result = simulate_wave_slot(context, planned, store, time=policy_time())

    assert isinstance(result, SyntheticWaveSlotExecutionResult)
    assert result.slot_index == 1
    assert result.execution_scope == "synthetic"
    assert result.production_wave_run == "NOT_RUN"
    assert result.live_limen_b6a == "NOT_RUN"
    assert len(read_verified_events(ledger_root, result.post_head)) == 4
    assert store.verify()["record_count"] == 2
    assert journal.synthetic_ledger_writes == 4
    assert journal.synthetic_receipt_writes == 1


def test_plain_candidate_cannot_plan_or_mutate_ledger(tmp_path, published_storage):
    selected_plan, _, _, policy_context, candidate, request, authorization = (
        setup_slot_one(tmp_path, published_storage)
    )
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )

    with pytest.raises(Exception, match="verified_candidate_required"):
        plan_wave_slot(
            context,
            candidate=candidate.candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            result_prefix=result_prefix,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=verified_application_authority(
                candidate, authorization
            ),
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=context.target_root / "staging",
        )

    assert not ledger_root.exists()


def test_candidate_request_mismatch_refuses_before_ledger_write(
    tmp_path, published_storage
):
    (
        selected_plan,
        _,
        _,
        policy_context,
        selected_candidate,
        request,
        authorization,
    ) = setup_slot_one(tmp_path, published_storage)
    different_candidate = candidates(tmp_path / "different")[1]
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )

    with pytest.raises(Exception, match="wave_slot_candidate_mismatch"):
        plan_wave_slot(
            context,
            candidate=different_candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            result_prefix=result_prefix,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=verified_application_authority(
                selected_candidate, authorization
            ),
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
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    planned = plan_wave_slot(
        context,
        candidate=candidate,
        wave_plan=selected_plan,
        slot_request=request,
        execution_authorization=authorization,
        result_prefix=result_prefix,
        policy_context=policy_context,
        policy_storage=published_storage,
        policy_time=policy_time(),
        application_authority=verified_application_authority(
            candidate, authorization
        ),
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging",
    )

    first = simulate_wave_slot(context, planned, store, time=policy_time())
    second = simulate_wave_slot(context, planned, store, time=policy_time())

    assert second.to_dict() == first.to_dict()
    assert len(read_verified_events(ledger_root, second.post_head)) == 4


def test_slot_plan_rechecks_expired_approval_and_jit_before_staging(
    tmp_path, published_storage
):
    selected_plan, _, _, policy_context, candidate, request, authorization = (
        setup_slot_one(tmp_path, published_storage)
    )
    journal = WaveEffectJournal()
    context = engine_context(tmp_path, journal)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    staging_parent = context.target_root / "staging"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )

    with pytest.raises(RALValidationError, match="authority_time_inactive"):
        plan_wave_slot(
            context,
            candidate=candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            result_prefix=result_prefix,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(now=400, expires_at=500),
            application_authority=verified_application_authority(
                candidate, authorization
            ),
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=staging_parent,
        )

    assert not staging_parent.exists()
    assert not ledger_root.exists()


def test_slot_commit_rechecks_expired_jit_before_append(tmp_path, published_storage):
    selected_plan, _, _, policy_context, candidate, request, authorization = (
        setup_slot_one(tmp_path, published_storage)
    )
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    planned = plan_wave_slot(
        context,
        candidate=candidate,
        wave_plan=selected_plan,
        slot_request=request,
        execution_authorization=authorization,
        result_prefix=result_prefix,
        policy_context=policy_context,
        policy_storage=published_storage,
        policy_time=policy_time(),
        application_authority=verified_application_authority(
            candidate, authorization
        ),
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging",
    )

    with pytest.raises(RALValidationError, match="authority_time_inactive"):
        simulate_wave_slot(
            context,
            planned,
            store,
            time=policy_time(now=400, expires_at=500),
        )

    assert not ledger_root.exists()


def test_slot_one_result_cannot_be_used_as_slot_three_predecessor(
    tmp_path, published_storage
):
    (
        selected_plan,
        selected_policy,
        approvals,
        policy_context,
        candidate_one,
        request_one,
        authorization_one,
    ) = setup_slot_one(tmp_path, published_storage)
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    empty_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    planned_one = plan_wave_slot(
        context,
        candidate=candidate_one,
        wave_plan=selected_plan,
        slot_request=request_one,
        execution_authorization=authorization_one,
        result_prefix=empty_prefix,
        policy_context=policy_context,
        policy_storage=published_storage,
        policy_time=policy_time(),
        application_authority=verified_application_authority(
            candidate_one, authorization_one
        ),
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging-one",
    )
    result_one = simulate_wave_slot(
        context, planned_one, store, time=policy_time()
    )
    candidate_three = candidates(tmp_path / "slot-three-candidate")[2]
    slot_three = selected_plan.ordered_slots[2]
    request_three = WaveSlotRequest.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-request/0.1",
            "request_id": "slot-request:forged-skip-two",
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": slot_three["slot_id"],
            "slot_index": 3,
            "candidate_ref": slot_three["candidate_ref"],
            "candidate_digest": slot_three["candidate_digest"],
            "application_ref": slot_three["application_ref"],
            "application_digest": slot_three["application_digest"],
            "predecessor_receipt_ref": result_one.result_id,
            "predecessor_receipt_digest": result_one.digest,
            "expected_ledger_state": {
                "expected_ledger_head": result_one.post_head,
                "cli_token": result_one.post_head,
                "ledger_event_count": 4,
            },
            "policy_ref": selected_plan.policy_ref,
            "policy_digest": selected_plan.policy_digest,
            "checkpoint_ref": selected_plan.checkpoint_ref,
            "checkpoint_digest": selected_plan.checkpoint_digest,
            "registry_generation_digest": selected_plan.registry_generation_digest,
            "registry_control_digest": selected_plan.registry_control_digest,
            "not_claimed": ["batch_execution", "rank", "authority"],
        }
    )
    intent = execution_intent(selected_plan, request_three, approvals[2])
    raw = raw_principal_item(
        intent, item_ref="user-item:slot-3", turn_id="turn:slot-3"
    )
    host = principal_host(raw)
    authorization_three = verify_slot_execution_authorization(
        execution_artifact(selected_plan, request_three, approvals[2], raw, host),
        selected_plan,
        request_three,
        approvals[2],
        selected_policy,
        checkpoint(),
        current_status(selected_plan, result_one.post_head),
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )

    prefix_after_one = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    with pytest.raises(RALValidationError, match="wave_predecessor_missing"):
        plan_wave_slot(
            context,
            candidate=candidate_three,
            wave_plan=selected_plan,
            slot_request=request_three,
            execution_authorization=authorization_three,
            result_prefix=prefix_after_one,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=verified_application_authority(
                candidate_three, authorization_three
            ),
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=context.target_root / "staging-three",
        )

    assert len(read_verified_events(ledger_root, result_one.post_head)) == 4
    assert store.get_slot_result("slot:2") is None
    assert store.get_slot_result("slot:3") is None


def test_raw_attacker_application_authority_cannot_use_valid_jit(
    tmp_path, published_storage
):
    selected_plan, _, _, policy_context, candidate, request, authorization = (
        setup_slot_one(tmp_path, published_storage)
    )
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    result_prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    attacker_authority = {
        **application_authority(candidate),
        "authority_id": "authority:attacker",
        "principal_ref": "principal:attacker",
        "authorship_attestation_ref": "attestation:attacker",
    }

    with pytest.raises(
        RALValidationError, match="verified_application_authority_required"
    ):
        plan_wave_slot(
            context,
            candidate=candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            result_prefix=result_prefix,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=attacker_authority,
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=context.target_root / "staging-attacker",
        )

    assert not ledger_root.exists()
    assert store.get_slot_request("slot:1") is None


def test_verified_synthetic_prefix_advances_exactly_slot_one_two_three(
    tmp_path, published_storage
):
    selected_plan, selected_policy, approvals, policy_context = setup_active_wave(
        tmp_path, published_storage
    )
    selected_candidates = candidates(tmp_path / "sequential-candidates")
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    results = []

    for index in (1, 2, 3):
        candidate = selected_candidates[index - 1]
        request = synthetic_request(selected_plan, index, prefix)
        authorization = verified_slot_authorization(
            selected_plan,
            selected_policy,
            approvals[index - 1],
            request,
            item_suffix=f"slot-{index}",
        )
        planned = plan_wave_slot(
            context,
            candidate=candidate,
            wave_plan=selected_plan,
            slot_request=request,
            execution_authorization=authorization,
            result_prefix=prefix,
            policy_context=policy_context,
            policy_storage=published_storage,
            policy_time=policy_time(),
            application_authority=verified_application_authority(
                candidate, authorization
            ),
            ctcl_receipt=CTCL,
            ledger_root=ledger_root,
            staging_parent=context.target_root / f"staging-{index}",
        )
        results.append(
            simulate_wave_slot(context, planned, store, time=policy_time())
        )
        prefix = verify_synthetic_wave_result_prefix(
            context, selected_plan, store, ledger_root
        )

    assert [value.slot_index for value in results] == [1, 2, 3]
    assert prefix.final_head == results[-1].post_head
    assert prefix.ledger_event_count == 12
    assert len(read_verified_events(ledger_root, prefix.final_head)) == 12
