from __future__ import annotations

import pytest
from test_registration_wave_intake import (
    CountingIdsFactory,
    claim,
    context,
    host,
    ids,
    item,
    raw_item,
)

from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_intake import (
    VerifiedPreparedCandidate,
    prepare_wave_candidate,
)
from sedb_ral.registration_wave_models import RegistrationWavePolicy
from sedb_ral.registration_wave_plan import (
    build_slot_request,
    build_wave_plan,
    verify_wave_receipt_prefix,
)

THREADS = (
    "10000000-0000-4000-8000-000000000001",
    "20000000-0000-4000-8000-000000000002",
    "30000000-0000-4000-8000-000000000003",
)


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def candidates(tmp_path) -> tuple[VerifiedPreparedCandidate, ...]:
    return tuple(
        prepare_wave_candidate(
            context(tmp_path / f"candidate-{index}"),
            claim(index),
            item(index),
            host(index),
            raw_item(index),
            CountingIdsFactory(ids(index)),
        )
        for index in (1, 2, 3)
    )


def policy(
    selected_candidates: tuple[VerifiedPreparedCandidate, ...],
) -> RegistrationWavePolicy:
    return RegistrationWavePolicy.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy/0.1",
            "policy_id": "policy:wave-1",
            "wave_id": "wave:synthetic:1",
            "ordered_application_digests": [
                candidate.application_digest for candidate in selected_candidates
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


def plan(tmp_path):
    selected = candidates(tmp_path)
    return build_wave_plan(
        selected, policy(selected), registry_status(), checkpoint()
    )


def ledger_state(head: str | None, count: int) -> dict[str, object]:
    return {
        "expected_ledger_head": head,
        "cli_token": "GENESIS" if head is None else head,
        "ledger_event_count": count,
    }


def test_build_wave_plan_binds_three_verified_candidates_in_equal_order(tmp_path):
    observed = plan(tmp_path)

    assert [slot["slot_index"] for slot in observed.ordered_slots] == [1, 2, 3]
    assert all("rank" not in slot for slot in observed.ordered_slots)
    assert observed.initial_ledger_state == ledger_state(None, 0)


def test_plain_self_sealed_candidates_cannot_build_plan(tmp_path):
    verified = candidates(tmp_path)

    with pytest.raises(RALValidationError, match="verified_candidate_required"):
        build_wave_plan(
            tuple(value.candidate for value in verified),
            policy(verified),
            registry_status(),
            checkpoint(),
        )


def test_policy_order_change_refuses_verified_candidate_plan(tmp_path):
    verified = candidates(tmp_path)
    changed = policy(verified).to_dict()
    changed["ordered_application_digests"] = list(
        reversed(changed["ordered_application_digests"])
    )
    changed_policy = RegistrationWavePolicy.sealed(changed)

    with pytest.raises(RALValidationError, match="wave_candidate_binding_mismatch"):
        build_wave_plan(verified, changed_policy, registry_status(), checkpoint())


def test_control_digest_is_not_genesis_ledger_head(tmp_path):
    selected = plan(tmp_path)
    prefix = verify_wave_receipt_prefix(selected, ())

    with pytest.raises(RALValidationError, match="wave_ledger_state_invalid"):
        build_slot_request(
            selected,
            1,
            prefix,
            ledger_state(selected.registry_control_digest, 0),
        )


def test_slot_one_requires_typed_genesis_and_empty_verified_prefix(tmp_path):
    selected = plan(tmp_path)
    prefix = verify_wave_receipt_prefix(selected, ())

    request = build_slot_request(selected, 1, prefix, ledger_state(None, 0))

    assert request.slot_index == 1
    assert request.predecessor_receipt_ref is None
    assert request.expected_ledger_state == ledger_state(None, 0)


def test_slot_three_cannot_use_current_h1_without_two_verified_receipts(tmp_path):
    selected = plan(tmp_path)
    empty_prefix = verify_wave_receipt_prefix(selected, ())

    with pytest.raises(RALValidationError, match="wave_predecessor_missing"):
        build_slot_request(
            selected, 3, empty_prefix, ledger_state(digest("h1"), 1)
        )
