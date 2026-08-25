from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from phase3a_operations_helpers import (
    initialized_operations_workspace,
    valid_operation_request,
    valid_operator_observation,
)

from sedb_ral.errors import RALValidationError
from sedb_ral.operations.models import OperationRequest, OperatorObservation
from sedb_ral.operations.store import OperationsStore


def lease_fixture(tmp_path):
    store = OperationsStore(initialized_operations_workspace(tmp_path))
    request = OperationRequest.from_dict(valid_operation_request())
    observation = OperatorObservation.from_dict(valid_operator_observation())
    store.submit_request(request)
    return store, request, observation


def test_concurrent_lease_has_exactly_one_winner(tmp_path):
    store, request, observation = lease_fixture(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(lambda _: store.acquire_lease(request, observation), range(2))
        )

    assert sum(item.acquired for item in results) == 1
    assert [item.error_code for item in results if not item.acquired] == [
        "operation_in_progress"
    ]
    assert len(tuple((store.workspace.root / "leases").glob("*.json"))) == 1


def test_operator_observation_must_match_request_before_lease(tmp_path):
    store, request, _ = lease_fixture(tmp_path)
    other = OperatorObservation.from_dict(
        valid_operator_observation(observation_id="operator-observation:other")
    )

    with pytest.raises(RALValidationError) as caught:
        store.acquire_lease(request, other)

    assert caught.value.code == "operation_operator_observation_mismatch"
    assert tuple((store.workspace.root / "leases").glob("*.json")) == ()


def test_release_is_immutable_audit_and_never_deletes_lease(tmp_path):
    store, request, observation = lease_fixture(tmp_path)
    lease = store.acquire_lease(request, observation)

    release = store.record_lease_release(request, str(lease.lease_digest))

    assert release["lease_digest"] == lease.lease_digest
    assert len(tuple((store.workspace.root / "leases").glob("*.json"))) == 1
    assert (
        len(tuple((store.workspace.root / "audit").glob("lease-release-*.json"))) == 1
    )
    repeated = store.acquire_lease(request, observation)
    assert repeated.acquired is False
    assert repeated.error_code == "operation_in_progress"
