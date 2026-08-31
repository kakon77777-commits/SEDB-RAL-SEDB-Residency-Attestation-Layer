from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from .canonical import canonical_bytes, sha256_ref
from .errors import RALValidationError
from .ledger import read_verified_events
from .limen_public_view import build_limen_public_view
from .projection import project_events
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_models import RegistrationWavePlan, WaveReadbackBundle
from .registration_wave_store import VerifiedSyntheticWaveSlotResult

_RAL_VIEW_SCHEMA_ID = "https://evemisslab.com/schemas/limen/ral-view-v0.2.json"


def _parse_plan(
    value: Mapping[str, object] | RegistrationWavePlan,
) -> RegistrationWavePlan:
    return (
        value
        if isinstance(value, RegistrationWavePlan)
        else RegistrationWavePlan.from_dict(value)
    )


def _verified_capabilities(
    plan: RegistrationWavePlan,
    values: object,
) -> tuple[VerifiedSyntheticWaveSlotResult, ...]:
    if (
        not isinstance(values, tuple)
        or not values
        or len(values) > 3
        or any(not isinstance(item, VerifiedSyntheticWaveSlotResult) for item in values)
    ):
        raise RALValidationError(
            "verified_synthetic_result_required",
            "readback requires one to three verifier-issued slot results",
        )
    capabilities = tuple(values)
    for index, capability in enumerate(capabilities, start=1):
        capability.verify()
        if (
            capability.prefix_plan_digest != plan.digest
            or capability.execution.plan.digest != plan.digest
            or capability.result.wave_plan_digest != plan.digest
            or capability.result.slot_index != index
            or capability.execution.request.slot_index != index
            or capability.execution.request.slot_id
            != plan.ordered_slots[index - 1]["slot_id"]
        ):
            raise RALValidationError(
                "wave_readback_result_mismatch",
                "slot result does not bind the contiguous Wave plan prefix",
            )
    return capabilities


def build_wave_readback_bundle(
    context: SyntheticWaveExecutionContext,
    ledger_root: Path,
    expected_head: str,
    plan: Mapping[str, object] | RegistrationWavePlan,
    slot_results: tuple[VerifiedSyntheticWaveSlotResult, ...],
) -> WaveReadbackBundle:
    parsed_plan = _parse_plan(plan)
    capabilities = _verified_capabilities(parsed_plan, slot_results)
    if not isinstance(expected_head, str) or not expected_head:
        raise RALValidationError(
            "wave_readback_head_invalid", "readback head must be non-empty"
        )
    final_capability = capabilities[-1]
    if final_capability.result.post_head != expected_head:
        raise RALValidationError(
            "wave_readback_head_mismatch",
            "final verified result does not bind the expected head",
        )

    canonical_root = Path(ledger_root)
    context.verify_before_io("wave_readback", canonical_root)
    events = read_verified_events(canonical_root, expected_head)
    previous_count = 0
    for index, capability in enumerate(capabilities, start=1):
        retained = tuple(capability.ledger_events)
        if (
            len(retained) <= previous_count
            or retained != tuple(events[: len(retained)])
            or capability.result.post_head
            != retained[-1]["integrity"]["chain_digest"]
            or capability.result.slot_index != index
        ):
            raise RALValidationError(
                "wave_readback_prefix_mismatch",
                "verified result and actual ledger prefix differ",
            )
        previous_count = len(retained)
    if tuple(final_capability.ledger_events) != events:
        raise RALValidationError(
            "wave_readback_prefix_mismatch",
            "final capability does not bind the complete current ledger",
        )

    projection = project_events(events)
    view = build_limen_public_view(
        projection,
        ledger_head=expected_head,
        sequence=len(events),
    )
    view_value = view.to_dict()
    if view_value["projection_conflicts"]:
        raise RALValidationError(
            "wave_readback_projection_conflict",
            "public projection contains a binding conflict",
        )
    source_events = [
        {"event_ref": str(event["event_id"]), "event_digest": sha256_ref(event)}
        for event in events
    ]
    slot_projection_digests = [
        {
            "slot_index": capability.result.slot_index,
            **capability.result.projection_digests,
        }
        for capability in capabilities
    ]
    seed = sha256_ref(
        {
            "wave_plan_digest": parsed_plan.digest,
            "expected_ledger_head": expected_head,
            "slot_result_digests": [
                capability.result.digest for capability in capabilities
            ],
            "public_view_digest": view.digest,
        }
    )
    return WaveReadbackBundle.sealed(
        {
            "schema": "sedb-ral.registration-wave-readback-bundle/0.1",
            "bundle_id": f"wave-readback:{seed.rsplit(':', 1)[-1][:24]}",
            "wave_plan_ref": f"registration-wave-plan:{parsed_plan.wave_id}",
            "wave_plan_digest": parsed_plan.digest,
            "expected_ledger_head": expected_head,
            "admitted_slot_indexes": [
                capability.result.slot_index for capability in capabilities
            ],
            "ral_view_schema_id": _RAL_VIEW_SCHEMA_ID,
            "raw_sha256": hashlib.sha256(canonical_bytes(view_value)).hexdigest(),
            "public_view_digest": view.digest,
            "ledger_head": view_value["ledger_head"],
            "binding_head": view_value["binding_head"],
            "authority_head": view_value["authority_head"],
            "source_events": source_events,
            "slot_projection_digests": slot_projection_digests,
            "production_wave_run": "NOT_RUN",
            "live_limen_b6a": "NOT_RUN",
            "not_claimed": [
                "live_limen_resolution",
                "production_admission",
                "private_access",
                "identity_merge",
            ],
        }
    )
