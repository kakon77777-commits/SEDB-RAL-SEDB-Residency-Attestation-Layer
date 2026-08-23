import json
from pathlib import Path

import pytest

from sedb_ral.adapters.codex_queue import normalize_codex_queue
from sedb_ral.delivery import evaluate_route_predicates, reconstruct_delivery

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


def test_presented_instance_mismatch_blocks_acknowledgement():
    state = reconstruct_delivery(
        [normalize_codex_queue(load("presented-instance-mismatch.json"))]
    )

    assert state.stage == "instance_presented"
    assert state.presented_instance_mismatch is True
    assert state.instance_acknowledged is None
    assert state.observed_origin == (
        "instance:other:04a94f5c-8bdc-4552-8fd0-2273d8fb72ae"
    )


def test_destination_route_is_ready_but_send_readiness_is_unmeasured():
    diagnostics = evaluate_route_predicates(
        {
            "peer_reachable": True,
            "target_lock_valid": True,
            "adapter_submits": True,
        }
    )

    assert diagnostics.destination_route_ready is True
    assert diagnostics.send_ready is None
    assert diagnostics.send_permitted is False


def test_unmeasured_adapter_submission_remains_null_and_fails_closed():
    diagnostics = evaluate_route_predicates(
        {
            "peer_reachable": True,
            "target_lock_valid": True,
            "adapter_submits": None,
        }
    )

    assert diagnostics.adapter_submits is None
    assert diagnostics.destination_route_ready is None
    assert diagnostics.send_permitted is False


@pytest.mark.parametrize("deciding_term", ["peer_reachable", "target_lock_valid", "adapter_submits"])
def test_each_false_route_term_is_solely_decisive(deciding_term: str):
    predicates: dict[str, bool | None] = {
        "peer_reachable": True,
        "target_lock_valid": True,
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
