from __future__ import annotations

import copy

import pytest

from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_models import (
    RegistrationWavePolicy,
    RegistrationWavePreparedCandidate,
    WaveSlotReceipt,
)
from sedb_ral.registration_wave_plan import (
    build_slot_request,
    build_wave_plan,
    derive_next_slot,
)

THREADS = (
    "10000000-0000-4000-8000-000000000001",
    "20000000-0000-4000-8000-000000000002",
    "30000000-0000-4000-8000-000000000003",
)


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def candidate(index: int) -> RegistrationWavePreparedCandidate:
    return RegistrationWavePreparedCandidate.sealed(
        {
            "schema": "sedb-ral.registration-wave-prepared-candidate/0.1",
            "candidate_id": f"candidate:slot-{index}",
            "claim_ref": f"claim:slot-{index}",
            "canonical_claim_digest": digest(f"claim-{index}"),
            "item_evidence_ref": f"item-evidence:slot-{index}",
            "item_evidence_digest": digest(f"item-{index}"),
            "host_v02_ref": f"observation:slot-{index}",
            "host_v02_digest": digest(f"host-{index}"),
            "compatibility_host_v01_ref": f"host-v01:slot-{index}",
            "compatibility_host_v01_digest": digest(f"host-v01-{index}"),
            "prepared_registration_ref": f"prepared:slot-{index}",
            "prepared_registration_digest": digest(f"prepared-{index}"),
            "application_ref": f"application:slot-{index}",
            "application_digest": digest(f"application-{index}"),
            "canonical_locator": THREADS[index - 1],
            "not_claimed": ["verified_identity", "private_access"],
        }
    )


def candidates() -> tuple[RegistrationWavePreparedCandidate, ...]:
    return tuple(candidate(index) for index in (1, 2, 3))


def policy() -> RegistrationWavePolicy:
    return RegistrationWavePolicy.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy/0.1",
            "policy_id": "policy:wave-1",
            "wave_id": "wave:synthetic:1",
            "ordered_application_digests": [
                candidate(index).application_digest for index in (1, 2, 3)
            ],
            "ordered_locators": list(THREADS),
            "allowed_actions": ["prepare", "readback", "admit_one"],
            "max_slots": 3,
            "batch_append": False,
            "capabilities": {
                "correction": False,
                "merge": False,
                "private_access": False,
                "network_send": False,
                "provider_call": False,
                "fabric_emit": False,
                "mcp_call": False,
                "cloud": False,
                "deletion": False,
            },
            "valid_from_ref": "ctcl:instant:policy-start",
            "expires_at_ref": "ctcl:instant:policy-end",
            "not_claimed": ["batch_authority", "private_access"],
        }
    )


def registry_status() -> dict[str, object]:
    return {
        "verified": True,
        "registry_control_digest": digest("registry-control"),
        "registry_generation_digest": digest("registry-generation"),
        "ledger_head": None,
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
    }


def checkpoint() -> dict[str, object]:
    return {
        "checkpoint_ref": "checkpoint:wave-1",
        "checkpoint_digest": digest("checkpoint"),
        "ledger_head": None,
    }


def plan():
    return build_wave_plan(candidates(), policy(), registry_status(), checkpoint())


def ledger_state(head: str | None, count: int) -> dict[str, object]:
    return {
        "expected_ledger_head": head,
        "cli_token": "GENESIS" if head is None else head,
        "ledger_event_count": count,
    }


def event(index: int) -> dict[str, object]:
    return {
        "event_ref": f"event:slot-{index}:1",
        "event_digest": digest(f"event-{index}"),
    }


def receipt(
    selected_plan,
    index: int,
    *,
    pre_head: str | None,
    post_head: str,
    status: str = "accepted",
) -> WaveSlotReceipt:
    return WaveSlotReceipt.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-receipt/0.1",
            "receipt_id": f"slot-receipt:{index}",
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "slot_id": f"slot:{index}",
            "slot_index": index,
            "slot_request_ref": f"slot-request:{index}",
            "slot_request_digest": digest(f"slot-request-{index}"),
            "execution_authorization_ref": f"execution-authorization:{index}",
            "execution_authorization_digest": digest(f"execution-authorization-{index}"),
            "application_approval_ref": f"approval:{index}",
            "application_approval_digest": digest(f"approval-{index}"),
            "pre_head": pre_head,
            "post_head": post_head,
            "appended_events": [event(index)],
            "projection_digests": {
                "application": digest(f"application-projection-{index}"),
                "resident": digest(f"resident-projection-{index}"),
                "instance": digest(f"instance-projection-{index}"),
                "address": digest(f"address-projection-{index}"),
                "binding": digest(f"binding-projection-{index}"),
            },
            "commit_receipt_ref": f"commit-receipt:{index}",
            "commit_receipt_digest": digest(f"commit-receipt-{index}"),
            "operation_receipt_ref": f"operation-receipt:{index}",
            "operation_receipt_digest": digest(f"operation-receipt-{index}"),
            "event_count_delta": 1,
            "limen_b6a_status": "current",
            "limen_b6a_result_ref": f"limen-result:{index}",
            "limen_b6a_result_digest": digest(f"limen-result-{index}"),
            "effect_deltas": {
                "resident": 1,
                "application": 1,
                "address": 1,
                "private": 0,
                "network": 0,
                "external": 0,
            },
            "status": status,
            "not_claimed": ["rank", "private_access"],
        }
    )


def test_build_wave_plan_binds_three_candidates_in_equal_standing_order():
    observed = plan()

    assert [slot["slot_index"] for slot in observed.ordered_slots] == [1, 2, 3]
    assert [slot["candidate_digest"] for slot in observed.ordered_slots] == [
        value.digest for value in candidates()
    ]
    assert all("rank" not in slot for slot in observed.ordered_slots)
    assert observed.initial_ledger_state == ledger_state(None, 0)


def test_changed_or_swapped_candidate_binding_refuses_plan():
    changed = list(candidates())
    value = changed[1].to_dict()
    value["application_digest"] = digest("changed-application")
    changed[1] = RegistrationWavePreparedCandidate.sealed(value)

    with pytest.raises(RALValidationError, match="wave_candidate_binding_mismatch"):
        build_wave_plan(tuple(changed), policy(), registry_status(), checkpoint())


def test_control_digest_is_not_genesis_ledger_head():
    selected = plan()
    invalid = ledger_state(selected.registry_control_digest, 0)

    with pytest.raises(RALValidationError, match="wave_ledger_state_invalid"):
        build_slot_request(selected, 1, None, invalid)


def test_slot_one_requires_typed_genesis_and_no_predecessor():
    selected = plan()

    request = build_slot_request(selected, 1, None, ledger_state(None, 0))

    assert request.slot_index == 1
    assert request.predecessor_receipt_ref is None
    assert request.expected_ledger_state == ledger_state(None, 0)


def test_slot_three_cannot_use_current_h1_without_slot_two_receipt():
    selected = plan()
    slot_one = receipt(selected, 1, pre_head=None, post_head=digest("h1"))

    with pytest.raises(RALValidationError, match="wave_predecessor_missing"):
        build_slot_request(selected, 3, slot_one, ledger_state(digest("h1"), 1))


def test_slot_two_binds_exact_slot_one_receipt_and_h1():
    selected = plan()
    slot_one = receipt(selected, 1, pre_head=None, post_head=digest("h1"))

    request = build_slot_request(
        selected, 2, slot_one, ledger_state(digest("h1"), 1)
    )

    assert request.predecessor_receipt_ref == slot_one.receipt_id
    assert request.predecessor_receipt_digest == slot_one.digest


def test_next_slot_is_derived_from_verified_receipt_and_event_prefix():
    selected = plan()
    slot_one = receipt(selected, 1, pre_head=None, post_head=digest("h1"))
    slot_two = receipt(
        selected, 2, pre_head=digest("h1"), post_head=digest("h2")
    )
    slot_three = receipt(
        selected, 3, pre_head=digest("h2"), post_head=digest("h3")
    )

    assert derive_next_slot(selected, (), ()) .slot_index == 1
    assert derive_next_slot(selected, (slot_one,), (event(1),)).slot_index == 2
    assert derive_next_slot(
        selected, (slot_one, slot_two), (event(1), event(2))
    ).slot_index == 3
    assert (
        derive_next_slot(
            selected,
            (slot_one, slot_two, slot_three),
            (event(1), event(2), event(3)),
        )
        is None
    )


def test_head_or_events_without_receipt_prefix_cannot_advance():
    selected = plan()

    with pytest.raises(RALValidationError, match="wave_receipt_prefix_invalid"):
        derive_next_slot(selected, (), (event(1),))


def test_substituted_or_nonaccepted_receipt_stops_prefix():
    selected = plan()
    wrong_status = receipt(
        selected,
        1,
        pre_head=None,
        post_head=digest("h1"),
        status="canonical_committed_readback_failed",
    )
    changed = receipt(selected, 1, pre_head=None, post_head=digest("h1")).to_dict()
    changed["wave_plan_digest"] = digest("another-plan")
    changed = WaveSlotReceipt.sealed(changed)

    for candidate_receipt in (wrong_status, changed):
        with pytest.raises(RALValidationError, match="wave_receipt_prefix_invalid"):
            derive_next_slot(selected, (candidate_receipt,), (event(1),))


def test_event_digest_mismatch_stops_prefix():
    selected = plan()
    slot_one = receipt(selected, 1, pre_head=None, post_head=digest("h1"))
    changed_event = copy.deepcopy(event(1))
    changed_event["event_digest"] = digest("other-event")

    with pytest.raises(RALValidationError, match="wave_receipt_prefix_invalid"):
        derive_next_slot(selected, (slot_one,), (changed_event,))
