import copy
import json
from pathlib import Path

import pytest

from sedb_ral.adapters.codex_queue import normalize_codex_queue
from sedb_ral.delivery import evaluate_route_predicates, reconstruct_delivery
from sedb_ral.errors import RALValidationError

from test_codex_queue_adapter import load

ROOT = Path(__file__).parents[1]


def test_reconstruction_advances_through_observed_delivery_stages():
    state = reconstruct_delivery(
        [normalize_codex_queue(load("materialized-and-acknowledged.json"))]
    )

    assert state.stage == "instance_acknowledged"
    assert state.transport_accepted is True
    assert state.conversation_materialized is True
    assert state.instance_presented is True
    assert state.instance_acknowledged is True
    assert [
        (item.stage, item.observer_ref, item.observed_time_ref)
        for item in state.transition_evidence
    ] == [
        (
            "transport_accepted",
            "adapter:codex_queue",
            "ctcl:instant:3634f90c-e2a6-4f47-af4a-a005ab0ac7d3",
        ),
        (
            "conversation_materialized",
            "adapter:codex_queue",
            "ctcl:instant:4fd1e86c-ae94-4b42-a28e-00cc6dc4cd4c",
        ),
        (
            "instance_presented",
            "adapter:codex_queue",
            "ctcl:instant:4fd1e86c-ae94-4b42-a28e-00cc6dc4cd4c",
        ),
        (
            "instance_acknowledged",
            "adapter:codex_queue",
            "ctcl:instant:4fd1e86c-ae94-4b42-a28e-00cc6dc4cd4c",
        ),
    ]


def test_presented_instance_mismatch_blocks_acknowledgement():
    state = reconstruct_delivery(
        [normalize_codex_queue(load("presented-instance-mismatch.json"))]
    )

    assert state.stage == "instance_presented"
    assert state.presented_instance_mismatch is True
    assert state.instance_acknowledged is None
    assert state.presented_instance_ref == (
        "instance:other:04a94f5c-8bdc-4552-8fd0-2273d8fb72ae"
    )
    assert state.observed_origin is None


def test_cross_target_observations_fail_closed_before_aggregation():
    accepted = normalize_codex_queue(load("transport-accepted.json"))
    other_target = copy.deepcopy(load("materialized-and-acknowledged.json"))
    other_target["target_thread_id"] = "019fe51e-9276-7f63-8c16-414624b7fa9e"
    other_target["transcript"]["thread_id"] = other_target["target_thread_id"]

    with pytest.raises(RALValidationError, match="delivery_observation_mismatch"):
        reconstruct_delivery([accepted, normalize_codex_queue(other_target)])


def test_destination_route_is_ready_but_send_readiness_is_unmeasured():
    diagnostics = evaluate_route_predicates(
        {
            "recipient_agent_reachable": True,
            "valid_target_lock": True,
            "adapter_submits": True,
        }
    )

    assert diagnostics.recipient_agent_reachable is True
    assert diagnostics.valid_target_lock is True
    assert diagnostics.destination_route_ready is True
    assert diagnostics.send_ready is None
    assert diagnostics.send_permitted is False


def test_unmeasured_adapter_submission_remains_null_and_fails_closed():
    diagnostics = evaluate_route_predicates(
        {
            "recipient_agent_reachable": True,
            "valid_target_lock": True,
            "adapter_submits": None,
        }
    )

    assert diagnostics.adapter_submits is None
    assert diagnostics.destination_route_ready is None
    assert diagnostics.send_permitted is False


@pytest.mark.parametrize(
    "deciding_term",
    ["recipient_agent_reachable", "valid_target_lock", "adapter_submits"],
)
def test_each_false_route_term_is_solely_decisive(deciding_term: str):
    predicates: dict[str, bool | None] = {
        "recipient_agent_reachable": True,
        "valid_target_lock": True,
        "adapter_submits": True,
    }
    predicates[deciding_term] = False

    diagnostics = evaluate_route_predicates(predicates)

    assert diagnostics.destination_route_ready is False
    assert diagnostics.send_permitted is False


def test_other_adapters_remain_unmeasured():
    matrix = json.loads(
        (ROOT / "fixtures/adapters/matrix.json").read_text(encoding="utf-8")
    )

    assert matrix["claude_session"]["observed_origin"] == "unmeasured"
    assert matrix["pmw_fabric"]["adapter_submits"] == "unmeasured"
    assert matrix["codex_queue"]["observed_origin"] == "observable"
    assert {
        row["observed_origin"] for row in matrix.values()
    } <= {
        "observable",
        "relay_only",
        "structurally_unavailable",
        "unmeasured",
    }
