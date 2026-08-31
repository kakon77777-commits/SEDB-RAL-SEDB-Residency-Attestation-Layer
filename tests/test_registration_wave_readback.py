from __future__ import annotations

import inspect

import pytest
from test_registration_wave_engine import (
    CTCL,
    candidates,
    engine_context,
    plan_wave_slot,
    policy_time,
    setup_active_wave,
    simulate_wave_slot,
    store_for_engine,
    synthetic_request,
    verified_application_authority,
    verified_slot_authorization,
    verify_synthetic_wave_result_prefix,
)
from test_registration_wave_engine import (
    published_storage as engine_published_storage,
)

from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_models import (
    SyntheticWaveSlotExecutionResult,
    WaveReadbackBundle,
)
from sedb_ral.registration_wave_readback import build_wave_readback_bundle


@pytest.fixture
def published_storage(tmp_path):
    return engine_published_storage.__wrapped__(tmp_path)


def wave_state(tmp_path, published_storage, slot_count: int):
    selected_plan, selected_policy, approvals, policy_context = setup_active_wave(
        tmp_path, published_storage
    )
    selected_candidates = candidates(tmp_path / "readback-candidates")
    context = engine_context(tmp_path)
    context.target_root.mkdir()
    store = store_for_engine(context, selected_plan.digest)
    ledger_root = context.target_root / "ledger"
    prefix = verify_synthetic_wave_result_prefix(
        context, selected_plan, store, ledger_root
    )
    capabilities = []
    for index in range(1, slot_count + 1):
        candidate = selected_candidates[index - 1]
        request = synthetic_request(selected_plan, index, prefix)
        authorization = verified_slot_authorization(
            selected_plan,
            selected_policy,
            approvals[index - 1],
            request,
            item_suffix=f"readback-slot-{index}",
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
            staging_parent=context.target_root / f"readback-staging-{index}",
        )
        simulate_wave_slot(context, planned, store, time=policy_time())
        capability = store.get_verified_slot_result(f"slot:{index}")
        assert capability is not None
        capabilities.append(capability)
        prefix = verify_synthetic_wave_result_prefix(
            context, selected_plan, store, ledger_root
        )
    return context, selected_plan, ledger_root, tuple(capabilities)


@pytest.mark.parametrize("slot_count", (1, 2, 3))
def test_bundle_reports_exact_synthetic_prefix_without_live_b6a(
    tmp_path, published_storage, slot_count
):
    context, selected_plan, ledger_root, capabilities = wave_state(
        tmp_path, published_storage, slot_count
    )
    expected_head = capabilities[-1].result.post_head

    result = build_wave_readback_bundle(
        context,
        ledger_root,
        expected_head,
        selected_plan,
        capabilities,
    )

    assert isinstance(result, WaveReadbackBundle)
    assert tuple(result.admitted_slot_indexes) == tuple(range(1, slot_count + 1))
    assert result.expected_ledger_head == expected_head
    assert result.ledger_head == expected_head
    assert result.production_wave_run == "NOT_RUN"
    assert result.live_limen_b6a == "NOT_RUN"
    assert len(result.slot_projection_digests) == slot_count
    assert len(result.source_events) == slot_count * 4


def test_readback_bundle_is_byte_deterministic(tmp_path, published_storage):
    context, selected_plan, ledger_root, capabilities = wave_state(
        tmp_path, published_storage, 1
    )
    expected_head = capabilities[-1].result.post_head

    first = build_wave_readback_bundle(
        context, ledger_root, expected_head, selected_plan, capabilities
    )
    second = build_wave_readback_bundle(
        context, ledger_root, expected_head, selected_plan, capabilities
    )

    assert first.to_dict() == second.to_dict()


def test_plain_self_sealed_result_is_not_readback_evidence_before_io(
    tmp_path, published_storage
):
    _context, selected_plan, ledger_root, capabilities = wave_state(
        tmp_path, published_storage, 1
    )
    plain = SyntheticWaveSlotExecutionResult.from_dict(
        capabilities[0].result.to_dict()
    )
    fresh = engine_context(tmp_path / "fresh-readback")

    with pytest.raises(RALValidationError, match="verified_synthetic_result_required"):
        build_wave_readback_bundle(
            fresh,
            ledger_root,
            capabilities[0].result.post_head,
            selected_plan,
            (plain,),
        )

    assert fresh.journal.nonzero_dimensions() == ()


def test_readback_api_and_schema_have_no_external_currentness_input(
    tmp_path, published_storage
):
    assert tuple(inspect.signature(build_wave_readback_bundle).parameters) == (
        "context",
        "ledger_root",
        "expected_head",
        "plan",
        "slot_results",
    )
    context, selected_plan, ledger_root, capabilities = wave_state(
        tmp_path, published_storage, 1
    )
    bundle = build_wave_readback_bundle(
        context,
        ledger_root,
        capabilities[0].result.post_head,
        selected_plan,
        capabilities,
    )

    for field in (
        "limen_observation",
        "fabric_delivery",
        "mneme_memory",
        "soacr_context",
        "private_capability",
    ):
        value = bundle.to_dict()
        value[field] = {"forged": True}
        value["bundle_digest"] = sha256_ref(
            {key: item for key, item in value.items() if key != "bundle_digest"}
        )
        with pytest.raises(RALValidationError, match="schema_invalid"):
            WaveReadbackBundle.from_dict(value)
