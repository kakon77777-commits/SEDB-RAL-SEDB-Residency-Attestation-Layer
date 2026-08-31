from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_phase3_registrar_recovery import _trim_to_valid_prefix
from test_registration_wave_authority import (
    PRINCIPAL_REF,
    principal_host,
    raw_principal_item,
    time_evidence,
)
from test_registration_wave_engine import (
    CTCL,
    engine_context,
    setup_slot_one,
    store_for_engine,
    verified_application_authority,
)
from test_registration_wave_engine import (
    published_storage as engine_published_storage,
)
from test_registration_wave_policy import policy_time

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registrar import commit_admission_plan
from sedb_ral.registration_wave_engine import (
    plan_wave_slot,
    simulate_wave_slot,
    verify_synthetic_wave_result_prefix,
)
from sedb_ral.registration_wave_models import (
    SyntheticWaveSlotRecoveryResult,
    WaveSlotReceipt,
    WaveSlotRecoveryAuthorization,
    WaveSlotRecoveryReceipt,
)
from sedb_ral.registration_wave_recovery import (
    VerifiedWaveSlotRecoveryAuthorization,
    inspect_wave_slot_prefix,
    plan_wave_continuation,
    recover_synthetic_wave_slot_result,
    verify_wave_slot_recovery_authorization,
)


@pytest.fixture
def published_storage(tmp_path):
    return engine_published_storage.__wrapped__(tmp_path)


def prepared_state(tmp_path, storage, *, mode: str):
    (
        selected_plan,
        _selected_policy,
        _approvals,
        policy_context,
        candidate,
        request,
        execution_authorization,
    ) = setup_slot_one(tmp_path, storage)
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
        execution_authorization=execution_authorization,
        result_prefix=result_prefix,
        policy_context=policy_context,
        policy_storage=storage,
        policy_time=policy_time(),
        application_authority=verified_application_authority(
            candidate, execution_authorization
        ),
        ctcl_receipt=CTCL,
        ledger_root=ledger_root,
        staging_parent=context.target_root / "staging",
    )
    if mode == "durable":
        simulate_wave_slot(context, planned, store, time=policy_time())
    else:
        commit_admission_plan(
            planned.ledger_root,
            planned.registrar_plan,
            planned.candidate.prepared,
            planned.decision,
            planned.application_authority.authority,
            planned.ctcl_receipt,
            verified_attestation_refs=planned.application_authority.attestation_refs,
        )
        if mode == "partial":
            _trim_to_valid_prefix(planned.ledger_root, keep=2)
    return context, planned, store


def recovery_intent(inspection, planned):
    return {
        "schema": "sedb-ral.registration-wave-slot-recovery-intent/0.1",
        "principal_ref": PRINCIPAL_REF,
        "wave_plan_digest": planned.wave_plan.digest,
        "slot_id": planned.slot_request.slot_id,
        "slot_request_digest": planned.slot_request.digest,
        "original_execution_authorization_digest": planned.execution_authorization.authorization.digest,
        "application_approval_digest": planned.execution_authorization.approval.approval.digest,
        "verified_prefix_digest": inspection.prefix_digest,
        "pre_head": planned.slot_request.expected_ledger_state[
            "expected_ledger_head"
        ],
        "post_head": inspection.current_head,
        "checkpoint_digest": planned.wave_plan.checkpoint_digest,
        "current_readback_digest": inspection.prefix_digest,
    }


def verified_recovery_authorization(inspection, planned):
    intent = recovery_intent(inspection, planned)
    raw = raw_principal_item(
        intent, item_ref="user-item:recovery", turn_id="turn:recovery"
    )
    host = principal_host(raw)
    artifact = WaveSlotRecoveryAuthorization.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-recovery-authorization/0.1",
            "recovery_authorization_id": "recovery-authorization:slot-1",
            "principal_ref": PRINCIPAL_REF,
            "wave_plan_ref": f"registration-wave-plan:{planned.wave_plan.wave_id}",
            "wave_plan_digest": planned.wave_plan.digest,
            "slot_id": planned.slot_request.slot_id,
            "slot_request_ref": planned.slot_request.request_id,
            "slot_request_digest": planned.slot_request.digest,
            "original_execution_authorization_ref": planned.execution_authorization.authorization.execution_authorization_id,
            "original_execution_authorization_digest": planned.execution_authorization.authorization.digest,
            "application_approval_ref": planned.execution_authorization.approval.approval.approval_id,
            "application_approval_digest": planned.execution_authorization.approval.approval.digest,
            "verified_prefix_digest": inspection.prefix_digest,
            "pre_head": planned.slot_request.expected_ledger_state[
                "expected_ledger_head"
            ],
            "post_head": inspection.current_head,
            "checkpoint_ref": planned.wave_plan.checkpoint_ref,
            "checkpoint_digest": planned.wave_plan.checkpoint_digest,
            "current_readback_digest": inspection.prefix_digest,
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "not_claimed": ["new_admission", "partial_prefix_acceptance"],
        }
    )
    return verify_wave_slot_recovery_authorization(
        artifact,
        inspection,
        planned,
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )


def test_durable_synthetic_result_is_idempotent_complete(tmp_path, published_storage):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="durable"
    )

    inspection = inspect_wave_slot_prefix(context, planned, store)

    assert inspection.status == "durable_receipt"
    assert inspection.current_head is not None


def test_complete_events_without_outer_result_require_recovery(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )

    inspection = inspect_wave_slot_prefix(context, planned, store)

    assert inspection.status == "recovery_required"
    assert inspection.current_head == planned.registrar_plan.candidate_head


def test_mid_chain_prefix_is_not_recovery_required_or_accepted(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="partial"
    )

    inspection = inspect_wave_slot_prefix(context, planned, store)

    assert inspection.status == "registrar_partial_transaction"


def test_missing_recovery_authorization_fails_before_new_io(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)
    fresh = engine_context(tmp_path / "fresh")

    with pytest.raises(RALValidationError, match="wave_recovery_authorization_missing"):
        recover_synthetic_wave_slot_result(
            fresh, None, inspection, planned, store, time=time_evidence()
        )

    assert fresh.journal.nonzero_dimensions() == ()


def test_verified_recovery_produces_only_synthetic_results(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)
    authorization = verified_recovery_authorization(inspection, planned)

    recovered = recover_synthetic_wave_slot_result(
        context,
        authorization,
        inspection,
        planned,
        store,
        time=time_evidence(),
    )

    assert isinstance(authorization, VerifiedWaveSlotRecoveryAuthorization)
    assert isinstance(recovered, SyntheticWaveSlotRecoveryResult)
    assert recovered.execution_scope == "synthetic"
    assert recovered.production_wave_run == "NOT_RUN"
    assert recovered.live_limen_b6a == "NOT_RUN"
    assert not isinstance(recovered, (WaveSlotReceipt, WaveSlotRecoveryReceipt))
    assert store.get_slot_result(str(planned.slot_request.slot_id)) is None
    assert (
        store.get_recovery_result(str(planned.slot_request.slot_id)).to_dict()
        == recovered.to_dict()
    )
    assert store.verify()["record_count"] == 2
    assert context.journal.refs("synthetic_receipt_writes") == (
        str(recovered.result_id),
    )


def test_recovery_rejects_capability_bound_to_changed_inspection(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)
    changed = replace(inspection, event_count=inspection.event_count + 1)
    authorization = verified_recovery_authorization(changed, planned)

    with pytest.raises(RALValidationError, match="wave_recovery_prefix_changed"):
        recover_synthetic_wave_slot_result(
            context,
            authorization,
            changed,
            planned,
            store,
            time=time_evidence(),
        )

    assert store.get_recovery_result(str(planned.slot_request.slot_id)) is None
    assert store.verify()["record_count"] == 1


def test_recovery_authority_is_not_issued_for_existing_durable_result(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="durable"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)

    with pytest.raises(RALValidationError, match="wave_recovery_state_invalid"):
        verified_recovery_authorization(inspection, planned)


def test_recovery_rechecks_expired_authority_before_result_write(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)
    authorization = verified_recovery_authorization(inspection, planned)

    with pytest.raises(RALValidationError, match="authority_time_inactive"):
        recover_synthetic_wave_slot_result(
            context,
            authorization,
            inspection,
            planned,
            store,
            time=time_evidence(now=400, valid_from=350, expires_at=500),
        )

    assert store.get_recovery_result(str(planned.slot_request.slot_id)) is None
    assert store.verify()["record_count"] == 1


def test_recovery_replay_is_idempotent(tmp_path, published_storage):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)
    authorization = verified_recovery_authorization(inspection, planned)

    first = recover_synthetic_wave_slot_result(
        context,
        authorization,
        inspection,
        planned,
        store,
        time=time_evidence(),
    )
    second = recover_synthetic_wave_slot_result(
        context,
        authorization,
        inspection,
        planned,
        store,
        time=time_evidence(),
    )

    assert first.to_dict() == second.to_dict()
    assert store.verify()["record_count"] == 2


def test_partial_prefix_cannot_plan_continuation_without_new_policy_authority(
    tmp_path, published_storage
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="partial"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)

    result = plan_wave_continuation(context, inspection, planned)

    assert result["continuation_status"] == "separate_authority_required"
    assert result["automatic_resume"] is False


@pytest.mark.parametrize("gate", ("store", "inspection"))
def test_resealed_recovery_result_cannot_substitute_recovery_authority(
    tmp_path, published_storage, gate
):
    context, planned, store = prepared_state(
        tmp_path, published_storage, mode="complete_without_result"
    )
    inspection = inspect_wave_slot_prefix(context, planned, store)
    authorization = verified_recovery_authorization(inspection, planned)
    recover_synthetic_wave_slot_result(
        context,
        authorization,
        inspection,
        planned,
        store,
        time=time_evidence(),
    )
    path = next((store.root / "records/recovery-results").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    result_value = dict(record["object"])
    result_value.pop("result_digest")
    result_value.update(
        {
            "recovery_authorization_ref": "recovery-authorization:attacker",
            "recovery_authorization_digest": sha256_ref(
                {"attacker": "recovery"}
            ),
        }
    )
    forged = SyntheticWaveSlotRecoveryResult.sealed(result_value)
    record["object"] = forged.to_dict()
    record["object_digest"] = forged.digest
    record["record_digest"] = sha256_ref(
        {key: value for key, value in record.items() if key != "record_digest"}
    )
    path.write_bytes(canonical_bytes(record))

    with pytest.raises(
        RALValidationError, match="verified_synthetic_recovery_required"
    ):
        if gate == "store":
            store.verify()
        else:
            inspect_wave_slot_prefix(context, planned, store)
