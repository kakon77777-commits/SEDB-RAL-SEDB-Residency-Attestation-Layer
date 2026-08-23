from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .adapters.codex_queue import AdapterObservation, TransitionEvidence
from .errors import RALValidationError


@dataclass(frozen=True)
class DeliveryState:
    delivery_id: str
    addressed_instance_ref: str
    target_thread_id: str
    stage: str
    transport_accepted: bool | None
    conversation_materialized: bool | None
    instance_presented: bool | None
    instance_acknowledged: bool | None
    presented_instance_ref: str | None
    presented_instance_mismatch: bool | None
    observed_origin: str | None
    transition_evidence: tuple[TransitionEvidence, ...]


@dataclass(frozen=True)
class RouteDiagnostics:
    recipient_agent_reachable: bool | None
    valid_target_lock: bool | None
    adapter_submits: bool | None
    destination_route_ready: bool | None
    send_ready: None = None
    send_permitted: bool = False


def _unanimous(values: Iterable[bool | None]) -> bool | None:
    known = {value for value in values if value is not None}
    if len(known) == 1:
        return known.pop()
    return None


def _one(values: Iterable[str | None]) -> str | None:
    known = {value for value in values if value is not None}
    if len(known) == 1:
        return known.pop()
    return None


def _tri_and(values: Iterable[bool | None]) -> bool | None:
    terms = tuple(values)
    if False in terms:
        return False
    if None in terms:
        return None
    return True


def _transition_evidence(
    observations: Iterable[AdapterObservation],
) -> tuple[TransitionEvidence, ...]:
    stage_order = {
        "transport_accepted": 1,
        "conversation_materialized": 2,
        "instance_presented": 3,
        "instance_acknowledged": 4,
    }
    return tuple(
        sorted(
            {
                evidence
                for observation in observations
                for evidence in observation.transition_evidence
            },
            key=lambda item: (
                stage_order[item.stage],
                item.observer_ref,
                item.observed_time_ref or "",
            ),
        )
    )


def evaluate_route_predicates(
    value: Mapping[str, object],
) -> RouteDiagnostics:
    expected = {
        "recipient_agent_reachable",
        "valid_target_lock",
        "adapter_submits",
    }
    if set(value) != expected or any(
        item is not None and type(item) is not bool for item in value.values()
    ):
        raise RALValidationError(
            "route_predicates_invalid",
            "route predicates must be exactly three boolean-or-null terms",
        )
    recipient_agent_reachable = value["recipient_agent_reachable"]
    valid_target_lock = value["valid_target_lock"]
    adapter_submits = value["adapter_submits"]
    return RouteDiagnostics(
        recipient_agent_reachable=recipient_agent_reachable,
        valid_target_lock=valid_target_lock,
        adapter_submits=adapter_submits,
        destination_route_ready=_tri_and(
            (
                recipient_agent_reachable,
                valid_target_lock,
                adapter_submits,
            )
        ),
    )


def reconstruct_delivery(
    observations: Iterable[AdapterObservation],
) -> DeliveryState:
    values = tuple(observations)
    if not values:
        raise RALValidationError(
            "delivery_observations_missing", "at least one observation is required"
        )
    delivery_ids = {item.delivery_id for item in values}
    addressed_instances = {item.addressed_instance_ref for item in values}
    target_thread_ids = {item.target_thread_id for item in values}
    if (
        len(delivery_ids) != 1
        or len(addressed_instances) != 1
        or len(target_thread_ids) != 1
    ):
        raise RALValidationError(
            "delivery_observation_mismatch",
            "observations must identify one delivery and addressed instance",
        )
    transport_accepted = _unanimous(
        item.transport_accepted for item in values
    )
    conversation_materialized = _unanimous(
        item.conversation_materialized for item in values
    )
    instance_presented = _unanimous(item.instance_presented for item in values)
    presented_instance_mismatch = _unanimous(
        item.presented_instance_mismatch for item in values
    )
    instance_acknowledged = _unanimous(
        item.instance_acknowledged for item in values
    )
    if presented_instance_mismatch is True:
        instance_acknowledged = None
    stage = "prepared"
    if transport_accepted is True:
        stage = "transport_accepted"
    if stage == "transport_accepted" and conversation_materialized is True:
        stage = "conversation_materialized"
    if stage == "conversation_materialized" and instance_presented is True:
        stage = "instance_presented"
    if stage == "instance_presented" and instance_acknowledged is True:
        stage = "instance_acknowledged"
    return DeliveryState(
        delivery_id=values[0].delivery_id,
        addressed_instance_ref=values[0].addressed_instance_ref,
        target_thread_id=values[0].target_thread_id,
        stage=stage,
        transport_accepted=transport_accepted,
        conversation_materialized=conversation_materialized,
        instance_presented=instance_presented,
        instance_acknowledged=instance_acknowledged,
        presented_instance_ref=_one(
            item.presented_instance_ref for item in values
        ),
        presented_instance_mismatch=presented_instance_mismatch,
        observed_origin=_one(item.observed_origin for item in values),
        transition_evidence=_transition_evidence(values),
    )
