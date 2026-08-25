from __future__ import annotations

import pytest
from phase3a_operations_helpers import valid_operation_request, valid_policy

from sedb_ral.operations.actions import (
    reject_application,
    suspend_address,
    withdraw_application,
)
from sedb_ral.operations.models import OperationRequest, OperationsPolicy


@pytest.mark.parametrize(
    ("kind", "function"),
    [
        ("reject", reject_application),
        ("withdraw", withdraw_application),
        ("suspend_address", suspend_address),
    ],
)
def test_unsupported_action_returns_typed_no_append_receipt(tmp_path, kind, function):
    ledger = tmp_path / "canonical-ledger"
    request = OperationRequest.from_dict(valid_operation_request(operation_kind=kind))
    policy = OperationsPolicy.from_dict(valid_policy())

    receipt = function(request=request, policy=policy)

    value = receipt.to_dict()
    assert value["outcome"] == "deferred"
    assert value["error_codes"] == ["operation_kind_not_implemented"]
    assert value["pre_head"] is None
    assert value["post_head"] is None
    assert value["side_effect_counters"] == {
        "synthetic_registry_writes": 0,
        "production_registry_writes": 0,
        "private_reads": 0,
        "network_calls": 0,
        "external_sends": 0,
        "fabric_events": 0,
    }
    assert not ledger.exists()
