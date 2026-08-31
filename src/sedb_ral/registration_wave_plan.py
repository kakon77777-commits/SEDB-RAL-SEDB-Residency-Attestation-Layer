from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .ledger import read_verified_events
from .operations.models import OperationReceipt
from .registrar import RegistrarCommitReceipt
from .registration_wave_intake import validate_exact_three_candidates
from .registration_wave_models import (
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    RegistrationWavePolicy,
    RegistrationWavePreparedCandidate,
    SlotExecutionAuthorization,
    WaveSlot,
    WaveSlotReceipt,
    WaveSlotRequest,
)

_PREFIX_CAPABILITY_TOKEN = object()


@dataclass(frozen=True)
class WaveReceiptEvidence:
    receipt: WaveSlotReceipt
    slot_request: WaveSlotRequest
    execution_authorization: SlotExecutionAuthorization
    application_approval: PrincipalApplicationApproval
    registrar_commit_receipt: RegistrarCommitReceipt
    operation_receipt: OperationReceipt
    ledger_root: Path


@dataclass(frozen=True)
class VerifiedWaveReceiptPrefix:
    plan_digest: str
    evidences: tuple[WaveReceiptEvidence, ...]
    final_head: str | None
    ledger_event_count: int
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _PREFIX_CAPABILITY_TOKEN:
            raise RALValidationError(
                "verified_receipt_prefix_required",
                "receipt prefix capability was not issued by the verifier",
            )

    def verify(self, plan: RegistrationWavePlan) -> None:
        material, final_head, event_count = _verify_evidence_sequence(
            plan, self.evidences
        )
        if (
            self.plan_digest != plan.digest
            or self.final_head != final_head
            or self.ledger_event_count != event_count
            or self.verification_digest != sha256_ref(material)
        ):
            raise RALValidationError(
                "verified_receipt_prefix_required",
                "verified receipt prefix is stale or mismatched",
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


def _verify_evidence_sequence(
    plan: RegistrationWavePlan,
    evidences: Sequence[WaveReceiptEvidence],
) -> tuple[dict[str, object], str | None, int]:
    previous_head: str | None = None
    event_count = 0
    evidence_digests: list[dict[str, object]] = []
    for index, evidence in enumerate(evidences, start=1):
        if index > 3:
            raise RALValidationError(
                "wave_receipt_prefix_invalid", "receipt prefix exceeds three slots"
            )
        if not isinstance(evidence, WaveReceiptEvidence):
            raise RALValidationError(
                "verified_receipt_prefix_required",
                "raw receipt mappings are not verified evidence",
            )
        receipt = _parse_receipt(evidence.receipt)
        request = WaveSlotRequest.from_dict(evidence.slot_request.to_dict())
        authorization = SlotExecutionAuthorization.from_dict(
            evidence.execution_authorization.to_dict()
        )
        approval = PrincipalApplicationApproval.from_dict(
            evidence.application_approval.to_dict()
        )
        operation = OperationReceipt.from_dict(evidence.operation_receipt.to_dict())
        operation_value = operation.to_dict()
        core = evidence.registrar_commit_receipt
        if not isinstance(core, RegistrarCommitReceipt):
            raise RALValidationError(
                "wave_receipt_evidence_mismatch",
                "registrar commit receipt type differs",
            )
        slot = plan.ordered_slots[index - 1]
        expected_plan_ref = _plan_ref(plan)
        if (
            request.wave_plan_ref != expected_plan_ref
            or request.wave_plan_digest != plan.digest
            or request.slot_id != slot["slot_id"]
            or request.slot_index != index
            or request.candidate_ref != slot["candidate_ref"]
            or request.candidate_digest != slot["candidate_digest"]
            or request.application_ref != slot["application_ref"]
            or request.application_digest != slot["application_digest"]
            or request.policy_ref != plan.policy_ref
            or request.policy_digest != plan.policy_digest
            or request.checkpoint_ref != plan.checkpoint_ref
            or request.checkpoint_digest != plan.checkpoint_digest
            or request.registry_generation_digest != plan.registry_generation_digest
            or request.registry_control_digest != plan.registry_control_digest
        ):
            raise RALValidationError(
                "wave_receipt_evidence_mismatch",
                "slot request does not bind the plan slot",
            )
        expected_predecessor = None if index == 1 else evidences[index - 2].receipt
        if (
            request.predecessor_receipt_ref
            != (None if expected_predecessor is None else expected_predecessor.receipt_id)
            or request.predecessor_receipt_digest
            != (None if expected_predecessor is None else expected_predecessor.digest)
            or request.expected_ledger_state["expected_ledger_head"] != previous_head
            or request.expected_ledger_state["ledger_event_count"] != event_count
        ):
            raise RALValidationError(
                "wave_receipt_evidence_mismatch",
                "slot request predecessor state differs",
            )
        if (
            approval.application_ref != slot["application_ref"]
            or approval.application_digest != slot["application_digest"]
            or approval.status != "active"
            or authorization.wave_plan_ref != expected_plan_ref
            or authorization.wave_plan_digest != plan.digest
            or authorization.slot_id != slot["slot_id"]
            or authorization.slot_index != index
            or authorization.operation_request_ref != request.request_id
            or authorization.operation_request_digest != request.digest
            or authorization.application_approval_ref != approval.approval_id
            or authorization.application_approval_digest != approval.digest
            or authorization.policy_ref != plan.policy_ref
            or authorization.policy_digest != plan.policy_digest
            or authorization.checkpoint_ref != plan.checkpoint_ref
            or authorization.checkpoint_digest != plan.checkpoint_digest
            or authorization.expected_ledger_head != previous_head
            or authorization.registry_control_digest != plan.registry_control_digest
            or authorization.status != "active"
        ):
            raise RALValidationError(
                "wave_receipt_evidence_mismatch",
                "approval or execution authorization differs",
            )
        core_digest = sha256_ref(core.to_dict())
        if (
            core.application_digest != slot["application_digest"]
            or core.source_head != previous_head
            or core.final_head != receipt.post_head
            or not core.committed
            or operation_value["request_digest"] != request.digest
            or operation_value["policy_digest"] != plan.policy_digest
            or operation_value["pre_head"] != previous_head
            or operation_value["post_head"] != receipt.post_head
            or operation_value["outcome"] != "complete"
            or operation_value["registrar_receipt_ref"]
            != receipt.commit_receipt_ref
            or operation_value["registrar_receipt_digest"] != core_digest
            or operation_value["error_codes"]
            or receipt.commit_receipt_digest != core_digest
            or receipt.operation_receipt_ref
            != f"registrar-operation-receipt:{operation_value['operation_id']}"
            or receipt.operation_receipt_digest != operation.digest
        ):
            raise RALValidationError(
                "wave_receipt_evidence_mismatch",
                "Core or operation receipt bindings differ",
            )
        events = read_verified_events(Path(evidence.ledger_root), receipt.post_head)
        tail_count = len(core.event_ids)
        if tail_count < 1 or len(events) < tail_count:
            raise RALValidationError(
                "wave_receipt_evidence_mismatch", "verified event suffix is absent"
            )
        tail = events[-tail_count:]
        observed_event_ids = tuple(str(value["event_id"]) for value in tail)
        observed_pairs = tuple(
            (str(value["event_id"]), sha256_ref(value)) for value in tail
        )
        receipt_pairs = tuple(_event_pair(value) for value in receipt.appended_events)
        if (
            observed_event_ids != core.event_ids
            or receipt_pairs != observed_pairs
            or receipt.event_count_delta != tail_count
            or receipt.wave_plan_ref != expected_plan_ref
            or receipt.wave_plan_digest != plan.digest
            or receipt.slot_id != slot["slot_id"]
            or receipt.slot_index != index
            or receipt.slot_request_ref != request.request_id
            or receipt.slot_request_digest != request.digest
            or receipt.execution_authorization_ref
            != authorization.execution_authorization_id
            or receipt.execution_authorization_digest != authorization.digest
            or receipt.application_approval_ref != approval.approval_id
            or receipt.application_approval_digest != approval.digest
            or receipt.pre_head != previous_head
            or receipt.status not in {"accepted", "recovered"}
            or receipt.limen_b6a_status != "current"
        ):
                raise RALValidationError(
                    "wave_receipt_evidence_mismatch",
                    "receipt does not extend the verified slot prefix",
                )
        event_count = len(events)
        previous_head = receipt.post_head
        evidence_digests.append(
            {
                "receipt_digest": receipt.digest,
                "slot_request_digest": request.digest,
                "execution_authorization_digest": authorization.digest,
                "application_approval_digest": approval.digest,
                "registrar_commit_receipt_digest": core_digest,
                "operation_receipt_digest": operation.digest,
                "ledger_head": receipt.post_head,
                "ledger_event_count": event_count,
            }
        )
    return (
        {
            "plan_digest": plan.digest,
            "evidence": evidence_digests,
            "final_head": previous_head,
            "ledger_event_count": event_count,
        },
        previous_head,
        event_count,
    )


def verify_wave_receipt_prefix(
    plan: Mapping[str, object] | RegistrationWavePlan,
    evidences: Sequence[WaveReceiptEvidence],
) -> VerifiedWaveReceiptPrefix:
    parsed_plan = _parse_plan(plan)
    material, final_head, event_count = _verify_evidence_sequence(
        parsed_plan, evidences
    )
    return VerifiedWaveReceiptPrefix(
        plan_digest=parsed_plan.digest,
        evidences=tuple(evidences),
        final_head=final_head,
        ledger_event_count=event_count,
        verification_digest=sha256_ref(material),
        _token=_PREFIX_CAPABILITY_TOKEN,
    )


def derive_next_slot(
    plan: Mapping[str, object] | RegistrationWavePlan,
    verified_prefix: object,
    legacy_events: object | None = None,
) -> WaveSlot | None:
    parsed_plan = _parse_plan(plan)
    if legacy_events is not None or not isinstance(
        verified_prefix, VerifiedWaveReceiptPrefix
    ):
        raise RALValidationError(
            "verified_receipt_prefix_required",
            "raw receipt/event values cannot advance the wave",
        )
    verified_prefix.verify(parsed_plan)
    index = len(verified_prefix.evidences) + 1
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
    verified_prefix: object,
    ledger_state: Mapping[str, object],
) -> WaveSlotRequest:
    parsed_plan = _parse_plan(plan)
    state = _validate_ledger_state(ledger_state)
    if not isinstance(verified_prefix, VerifiedWaveReceiptPrefix):
        raise RALValidationError(
            "verified_receipt_prefix_required",
            "slot requests require a verified receipt prefix",
        )
    verified_prefix.verify(parsed_plan)
    if slot_index not in (1, 2, 3):
        raise RALValidationError(
            "wave_slot_index_invalid", "slot index must be 1, 2, or 3"
        )
    expected_prefix_length = slot_index - 1
    if len(verified_prefix.evidences) != expected_prefix_length:
        raise RALValidationError(
            "wave_predecessor_missing",
            "verified prefix does not end immediately before the requested slot",
        )
    parsed_predecessor = (
        None
        if not verified_prefix.evidences
        else verified_prefix.evidences[-1].receipt
    )
    if slot_index == 1:
        if (
            parsed_predecessor is not None
            or state != parsed_plan.initial_ledger_state
            or verified_prefix.final_head is not None
            or verified_prefix.ledger_event_count != 0
        ):
            raise RALValidationError(
                "wave_ledger_state_invalid", "slot 1 requires exact GENESIS state"
            )
    else:
        if (
            parsed_predecessor is None
            or verified_prefix.final_head != state["expected_ledger_head"]
            or verified_prefix.ledger_event_count
            != state["ledger_event_count"]
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
