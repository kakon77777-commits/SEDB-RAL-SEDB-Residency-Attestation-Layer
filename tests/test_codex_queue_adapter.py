import copy
import json
from pathlib import Path

import pytest

from sedb_ral.adapters.codex_queue import normalize_codex_queue
from sedb_ral.errors import RALValidationError

ROOT = Path(__file__).parents[1]


def load(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / "fixtures/adapters/codex-queue" / name).read_text(
            encoding="utf-8"
        )
    )


def test_queue_exit_zero_observes_transport_acceptance():
    observation = normalize_codex_queue(load("transport-accepted.json"))

    assert observation.delivery_id == "delivery:codex-queue:0001"
    assert observation.transport_accepted is True
    assert observation.conversation_materialized is None
    assert observation.observed_origin is None


def test_complete_transcript_materializes_body_after_eleven_minutes():
    observation = normalize_codex_queue(
        load("materialized-and-acknowledged.json")
    )

    assert observation.materialization_delay_ms == 660000
    assert observation.conversation_materialized is True
    assert observation.instance_presented is True
    assert observation.instance_acknowledged is True
    assert observation.observed_origin == (
        "instance:recipient:0d7ccdd2-1adb-4c49-8e69-648a67ec28b9"
    )
    assert observation.session_file_completeness == "indeterminate"


def test_prefix_collision_is_not_a_full_target_thread_match():
    observation = normalize_codex_queue(load("prefix-collision.json"))

    assert observation.target_thread_match is False
    assert observation.conversation_materialized is None


def test_partial_transcript_does_not_advance_delivery_stages():
    observation = normalize_codex_queue(load("partial-transcript.json"))

    assert observation.conversation_materialized is None
    assert observation.instance_presented is None


@pytest.mark.parametrize("field", ["provider_session_path", "claimed_origin"])
def test_normalizer_rejects_unsanitized_or_claimed_fields(field: str):
    captured = copy.deepcopy(load("transport-accepted.json"))
    captured[field] = "not-observation-evidence"

    with pytest.raises(RALValidationError, match="schema_invalid"):
        normalize_codex_queue(captured)


def test_normalizer_rejects_a_target_thread_prefix():
    captured = copy.deepcopy(load("transport-accepted.json"))
    captured["target_thread_id"] = "019fe51e"

    with pytest.raises(RALValidationError, match="schema_invalid"):
        normalize_codex_queue(captured)
