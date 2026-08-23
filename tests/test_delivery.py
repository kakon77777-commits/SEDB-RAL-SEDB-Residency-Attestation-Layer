import copy
import json
from pathlib import Path

import pytest

import sedb_ral.delivery as delivery_module
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

    delivery_module.validate_adapter_matrix(matrix)
    routes = {row["route_id"]: row for row in matrix["routes"]}
    assert routes["claude_session_to_claude_conversation"][
        "adapter_submits"
    ] == {
        "measurement_status": "unmeasured",
        "observed_value": None,
        "evidence_refs": [],
        "reason": None,
    }
    assert routes["codex_queue_to_codex_conversation"]["adapter_submits"] == {
        "measurement_status": "observable",
        "observed_value": True,
        "evidence_refs": [
            "fixture:adapters/codex-queue/transport-accepted.json"
        ],
        "reason": None,
    }
    pmw = routes["pmw_fabric_herdr_to_codex_tui"]["adapter_submits"]
    assert pmw["measurement_status"] == "observable"
    assert pmw["observed_value"] is False
    assert set(pmw["evidence_refs"]) == {
        "corpus:incidents.jsonl#24",
        "evidence:own_execution:incident-24",
    }
    assert {
        measurement["measurement_status"]
        for row in routes.values()
        for measurement in (row["adapter_submits"], row["observed_origin"])
    } <= {
        "observable",
        "relay_only",
        "structurally_unavailable",
        "unmeasured",
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "unmeasured",
        True,
        1,
        None,
        {"measurement_status": {"nested": "wrong"}, "observed_value": None},
    ],
)
def test_every_adapter_submits_value_is_strictly_validated(invalid):
    matrix = json.loads(
        (ROOT / "fixtures/adapters/matrix.json").read_text(encoding="utf-8")
    )
    matrix["routes"][0]["adapter_submits"] = invalid

    with pytest.raises(RALValidationError, match="schema_invalid"):
        delivery_module.validate_adapter_matrix(matrix)


def test_route_matrix_feeds_only_strict_boolean_or_null_to_diagnostics():
    matrix = json.loads(
        (ROOT / "fixtures/adapters/matrix.json").read_text(encoding="utf-8")
    )

    assert delivery_module.matrix_adapter_submits(
        matrix, "codex_queue_to_codex_conversation"
    ) is True
    assert delivery_module.matrix_adapter_submits(
        matrix, "pmw_fabric_herdr_to_codex_tui"
    ) is False
    assert delivery_module.matrix_adapter_submits(
        matrix, "claude_session_to_claude_conversation"
    ) is None
    diagnostics = evaluate_route_predicates(
        {
            "recipient_agent_reachable": True,
            "valid_target_lock": True,
            "adapter_submits": delivery_module.matrix_adapter_submits(
                matrix, "pmw_fabric_herdr_to_codex_tui"
            ),
        }
    )
    assert diagnostics.destination_route_ready is False
