from __future__ import annotations

from collections.abc import Mapping, Sequence

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .registration_wave_intake import validate_exact_three_candidates
from .registration_wave_models import (
    RegistrationWavePlan,
    RegistrationWavePolicy,
    RegistrationWavePreparedCandidate,
    WaveSlot,
    WaveSlotReceipt,
    WaveSlotRequest,
)


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("wave plan input must remain an object")
    return canonical


def _plan_ref(plan: RegistrationWavePlan) -> str:
    return f"registration-wave-plan:{plan.wave_id}"


def _parse_plan(
    value: Mapping[str, object] | RegistrationWavePlan,
) -> RegistrationWavePlan:
    return value if isinstance(value, RegistrationWavePlan) else RegistrationWavePlan.from_dict(value)


def _parse_policy(
    value: Mapping[str, object] | RegistrationWavePolicy,
) -> RegistrationWavePolicy:
    return value if isinstance(value, RegistrationWavePolicy) else RegistrationWavePolicy.from_dict(value)


def _parse_receipt(
    value: Mapping[str, object] | WaveSlotReceipt,
) -> WaveSlotReceipt:
    return value if isinstance(value, WaveSlotReceipt) else WaveSlotReceipt.from_dict(value)


def _validate_registry_status(value: Mapping[str, object]) -> dict[str, object]:
    canonical = _canonical_object(value)
    required = {
        "verified",
        "registry_control_digest",
        "registry_generation_digest",
        "ledger_head",
        "ledger_event_count",
        "application_count",
        "resident_count",
        "address_count",
    }
    if set(canonical) != required or canonical["verified"] is not True:
        raise RALValidationError(
            "wave_registry_status_invalid", "registry status is incomplete"
        )
    if (
        canonical["ledger_head"] is not None
        or any(
            canonical[name] != 0
            for name in (
                "ledger_event_count",
                "application_count",
                "resident_count",
                "address_count",
            )
        )
    ):
        raise RALValidationError(
            "wave_registry_not_empty", "Wave 1 requires an empty registry"
        )
    return canonical


def _validate_checkpoint(value: Mapping[str, object]) -> dict[str, object]:
    canonical = _canonical_object(value)
    if set(canonical) != {"checkpoint_ref", "checkpoint_digest", "ledger_head"}:
        raise RALValidationError(
            "wave_checkpoint_invalid", "checkpoint fields differ"
        )
    if (
        not isinstance(canonical["checkpoint_ref"], str)
        or not canonical["checkpoint_ref"]
        or not isinstance(canonical["checkpoint_digest"], str)
        or not canonical["checkpoint_digest"]
        or canonical["ledger_head"] is not None
    ):
        raise RALValidationError(
            "wave_checkpoint_invalid", "checkpoint is not bound to H0"
        )
    return canonical


def build_wave_plan(
    candidates: Sequence[
        Mapping[str, object] | RegistrationWavePreparedCandidate
    ],
    policy: Mapping[str, object] | RegistrationWavePolicy,
    registry_status: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> RegistrationWavePlan:
    parsed_candidates = validate_exact_three_candidates(candidates)
    parsed_policy = _parse_policy(policy)
    status = _validate_registry_status(registry_status)
    verified_checkpoint = _validate_checkpoint(checkpoint)
    if list(parsed_policy.ordered_application_digests) != [
        candidate.application_digest for candidate in parsed_candidates
    ] or list(parsed_policy.ordered_locators) != [
        candidate.canonical_locator for candidate in parsed_candidates
    ]:
        raise RALValidationError(
            "wave_candidate_binding_mismatch",
            "policy and candidate order differ",
        )
    slots = [
        {
            "slot_id": f"slot:{index}",
            "slot_index": index,
            "candidate_ref": candidate.candidate_id,
            "candidate_digest": candidate.digest,
            "application_ref": candidate.application_ref,
            "application_digest": candidate.application_digest,
            "host_observation_ref": candidate.host_v02_ref,
            "host_observation_digest": candidate.host_v02_digest,
        }
        for index, candidate in enumerate(parsed_candidates, start=1)
    ]
    return RegistrationWavePlan.sealed(
        {
            "schema": "sedb-ral.registration-wave-plan/0.1",
            "wave_id": parsed_policy.wave_id,
            "ordered_slots": slots,
            "initial_ledger_state": {
                "expected_ledger_head": None,
                "cli_token": "GENESIS",
                "ledger_event_count": 0,
            },
            "registry_control_digest": status["registry_control_digest"],
            "registry_generation_digest": status["registry_generation_digest"],
            "policy_ref": parsed_policy.policy_id,
            "policy_digest": parsed_policy.digest,
            "checkpoint_ref": verified_checkpoint["checkpoint_ref"],
            "checkpoint_digest": verified_checkpoint["checkpoint_digest"],
            "terminal_boundary": "after_slot_3_or_stop",
            "not_claimed": ["rank", "seniority", "authority", "continuity"],
        }
    )


def _event_pair(value: Mapping[str, object]) -> tuple[str, str]:
    canonical = _canonical_object(value)
    if set(canonical) != {"event_ref", "event_digest"} or any(
        not isinstance(canonical[name], str) or not canonical[name]
        for name in canonical
    ):
        raise RALValidationError(
            "wave_receipt_prefix_invalid", "event evidence pair is invalid"
        )
    return str(canonical["event_ref"]), str(canonical["event_digest"])


def _verified_receipt_prefix(
    plan: RegistrationWavePlan,
    slot_receipts: Sequence[Mapping[str, object] | WaveSlotReceipt],
    events: Sequence[Mapping[str, object]],
) -> tuple[WaveSlotReceipt, ...]:
    parsed = tuple(_parse_receipt(value) for value in slot_receipts)
    observed_events = tuple(_event_pair(value) for value in events)
    expected_events: list[tuple[str, str]] = []
    previous_head: str | None = None
    for index, receipt in enumerate(parsed, start=1):
        if index > 3:
            raise RALValidationError(
                "wave_receipt_prefix_invalid", "receipt prefix exceeds three slots"
            )
        slot = plan.ordered_slots[index - 1]
        if (
            receipt.wave_plan_ref != _plan_ref(plan)
            or receipt.wave_plan_digest != plan.digest
            or receipt.slot_id != slot["slot_id"]
            or receipt.slot_index != index
            or receipt.pre_head != previous_head
            or receipt.status not in {"accepted", "recovered"}
            or receipt.limen_b6a_status != "current"
        ):
            raise RALValidationError(
                "wave_receipt_prefix_invalid",
                "receipt does not extend the verified slot prefix",
            )
        appended = tuple(_event_pair(value) for value in receipt.appended_events)
        if receipt.event_count_delta != len(appended):
            raise RALValidationError(
                "wave_receipt_prefix_invalid", "event count delta differs"
            )
        expected_events.extend(appended)
        previous_head = receipt.post_head
    if tuple(expected_events) != observed_events:
        raise RALValidationError(
            "wave_receipt_prefix_invalid", "event history differs from receipts"
        )
    return parsed


def derive_next_slot(
    plan: Mapping[str, object] | RegistrationWavePlan,
    slot_receipts: Sequence[Mapping[str, object] | WaveSlotReceipt],
    events: Sequence[Mapping[str, object]],
) -> WaveSlot | None:
    parsed_plan = _parse_plan(plan)
    verified = _verified_receipt_prefix(parsed_plan, slot_receipts, events)
    index = len(verified) + 1
    if index == 4:
        return None
    return WaveSlot.from_dict(parsed_plan.ordered_slots[index - 1])


def _validate_ledger_state(value: Mapping[str, object]) -> dict[str, object]:
    canonical = _canonical_object(value)
    if set(canonical) != {
        "expected_ledger_head",
        "cli_token",
        "ledger_event_count",
    }:
        raise RALValidationError(
            "wave_ledger_state_invalid", "ledger state fields differ"
        )
    head = canonical["expected_ledger_head"]
    token = canonical["cli_token"]
    count = canonical["ledger_event_count"]
    if (
        (head is not None and (not isinstance(head, str) or not head))
        or not isinstance(token, str)
        or not token
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or (head is None and (token != "GENESIS" or count != 0))
        or (head is not None and token != head)
    ):
        raise RALValidationError(
            "wave_ledger_state_invalid", "ledger state is not typed"
        )
    return canonical


def build_slot_request(
    plan: Mapping[str, object] | RegistrationWavePlan,
    slot_index: int,
    predecessor: Mapping[str, object] | WaveSlotReceipt | None,
    ledger_state: Mapping[str, object],
) -> WaveSlotRequest:
    parsed_plan = _parse_plan(plan)
    state = _validate_ledger_state(ledger_state)
    if slot_index not in (1, 2, 3):
        raise RALValidationError(
            "wave_slot_index_invalid", "slot index must be 1, 2, or 3"
        )
    parsed_predecessor = None if predecessor is None else _parse_receipt(predecessor)
    if slot_index == 1:
        if parsed_predecessor is not None or state != parsed_plan.initial_ledger_state:
            raise RALValidationError(
                "wave_ledger_state_invalid", "slot 1 requires exact GENESIS state"
            )
    else:
        expected_slot = parsed_plan.ordered_slots[slot_index - 2]
        if (
            parsed_predecessor is None
            or parsed_predecessor.wave_plan_ref != _plan_ref(parsed_plan)
            or parsed_predecessor.wave_plan_digest != parsed_plan.digest
            or parsed_predecessor.slot_index != slot_index - 1
            or parsed_predecessor.slot_id != expected_slot["slot_id"]
            or parsed_predecessor.status not in {"accepted", "recovered"}
            or parsed_predecessor.limen_b6a_status != "current"
            or parsed_predecessor.post_head != state["expected_ledger_head"]
        ):
            raise RALValidationError(
                "wave_predecessor_missing",
                "exact predecessor receipt and head are required",
            )
    slot = parsed_plan.ordered_slots[slot_index - 1]
    predecessor_ref = (
        None if parsed_predecessor is None else parsed_predecessor.receipt_id
    )
    predecessor_digest = (
        None if parsed_predecessor is None else parsed_predecessor.digest
    )
    seed = sha256_ref(
        {
            "wave_plan_digest": parsed_plan.digest,
            "slot_index": slot_index,
            "predecessor_receipt_digest": predecessor_digest,
            "expected_ledger_state": state,
        }
    )
    return WaveSlotRequest.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-request/0.1",
            "request_id": f"slot-request:{seed.rsplit(':', 1)[-1][:24]}",
            "wave_plan_ref": _plan_ref(parsed_plan),
            "wave_plan_digest": parsed_plan.digest,
            "slot_id": slot["slot_id"],
            "slot_index": slot_index,
            "candidate_ref": slot["candidate_ref"],
            "candidate_digest": slot["candidate_digest"],
            "application_ref": slot["application_ref"],
            "application_digest": slot["application_digest"],
            "predecessor_receipt_ref": predecessor_ref,
            "predecessor_receipt_digest": predecessor_digest,
            "expected_ledger_state": state,
            "policy_ref": parsed_plan.policy_ref,
            "policy_digest": parsed_plan.policy_digest,
            "checkpoint_ref": parsed_plan.checkpoint_ref,
            "checkpoint_digest": parsed_plan.checkpoint_digest,
            "registry_generation_digest": parsed_plan.registry_generation_digest,
            "registry_control_digest": parsed_plan.registry_control_digest,
            "not_claimed": ["batch_execution", "rank", "authority"],
        }
    )
