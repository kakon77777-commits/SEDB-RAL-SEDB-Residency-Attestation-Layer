from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..canonical import canonical_bytes, loads_strict
from ..contracts import validate_contract
from ..errors import RALValidationError


@dataclass(frozen=True)
class AdapterObservation:
    delivery_id: str
    addressed_instance_ref: str
    target_thread_id: str
    target_thread_match: bool | None
    transport_accepted: bool | None
    conversation_materialized: bool | None
    instance_presented: bool | None
    instance_acknowledged: bool | None
    presented_instance_ref: str | None
    presented_instance_mismatch: bool | None
    observed_origin: str | None
    materialization_delay_ms: int | None
    session_file_completeness: str | None


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    normalized = loads_strict(canonical_bytes(value).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise RALValidationError(
            "adapter_observation_not_object",
            "captured adapter observation must remain an object",
        )
    return normalized


def normalize_codex_queue(value: Mapping[str, object]) -> AdapterObservation:
    captured = _canonical_object(value)
    validate_contract("adapter-observation.schema.json", captured)
    queue = captured["queue"]
    transport_accepted = (
        None if queue is None else queue["exit_code"] == 0
    )
    transcript = captured["transcript"]
    session_file = captured["session_file"]
    conversation_materialized = None
    instance_presented = None
    instance_acknowledged = None
    presented_instance_ref = None
    presented_instance_mismatch = None
    observed_origin = None
    materialization_delay_ms = None
    target_thread_match = None
    if transcript is not None and transcript["completeness"] == "complete":
        target_thread_match = (
            transcript["thread_id"] == captured["target_thread_id"]
        )
    if (
        transcript is not None
        and transcript["completeness"] == "complete"
        and transcript["thread_id"] == captured["target_thread_id"]
        and transcript["message_digest"] == captured["message_digest"]
    ):
        conversation_materialized = True
        if queue is not None:
            materialization_delay_ms = (
                transcript["captured_at_ms"] - queue["captured_at_ms"]
            )
        presented_instance_ref = transcript["presented_instance_ref"]
        if presented_instance_ref is not None:
            instance_presented = True
            presented_instance_mismatch = (
                presented_instance_ref != captured["addressed_instance_ref"]
            )
            observed_origin = presented_instance_ref
            if (
                not presented_instance_mismatch
                and transcript["acknowledged_instance_ref"]
                == captured["addressed_instance_ref"]
            ):
                instance_acknowledged = True
    return AdapterObservation(
        delivery_id=captured["delivery_id"],
        addressed_instance_ref=captured["addressed_instance_ref"],
        target_thread_id=captured["target_thread_id"],
        target_thread_match=target_thread_match,
        transport_accepted=transport_accepted,
        conversation_materialized=conversation_materialized,
        instance_presented=instance_presented,
        instance_acknowledged=instance_acknowledged,
        presented_instance_ref=presented_instance_ref,
        presented_instance_mismatch=presented_instance_mismatch,
        observed_origin=observed_origin,
        materialization_delay_ms=materialization_delay_ms,
        session_file_completeness=(
            None if session_file is None else session_file["completeness"]
        ),
    )
