from __future__ import annotations

from ..errors import RALValidationError
from ..registry_root_contracts import bind_document_digest
from .models import OperationReceipt, OperationRequest, OperationsPolicy


def _unsupported(
    *,
    request: OperationRequest,
    policy: OperationsPolicy,
    expected_kind: str,
) -> OperationReceipt:
    request_value = request.to_dict()
    if request_value["operation_kind"] != expected_kind:
        raise RALValidationError(
            "operations_request_kind_mismatch", "action request kind differs"
        )
    if request_value["policy_digest"] != policy.digest:
        raise RALValidationError(
            "operations_policy_stale", "action request binds another policy"
        )
    value = bind_document_digest(
        {
            "schema": "sedb-ral.registrar-operation-receipt/0.1",
            "operation_id": request_value["operation_id"],
            "request_digest": request.digest,
            "policy_digest": policy.digest,
            "operations_generation": request_value["operations_generation"],
            "registry_id": request_value["registry_id"],
            "pre_head": None,
            "post_head": None,
            "outcome": "deferred",
            "registrar_receipt_ref": None,
            "registrar_receipt_digest": None,
            "projection_ref": None,
            "projection_digest": None,
            "error_codes": ["operation_kind_not_implemented"],
            "side_effect_counters": {
                "synthetic_registry_writes": 0,
                "production_registry_writes": 0,
                "private_reads": 0,
                "network_calls": 0,
                "external_sends": 0,
                "fabric_events": 0,
            },
            "completed_time_ref": request_value["created_time_ref"],
            "not_claimed": [
                "production_activation",
                "canonical_commit",
                "real_applicant",
                "private_access",
                "fabric_adoption",
            ],
        },
        "receipt_digest",
    )
    return OperationReceipt.from_dict(value)


def reject_application(
    *, request: OperationRequest, policy: OperationsPolicy
) -> OperationReceipt:
    return _unsupported(request=request, policy=policy, expected_kind="reject")


def withdraw_application(
    *, request: OperationRequest, policy: OperationsPolicy
) -> OperationReceipt:
    return _unsupported(request=request, policy=policy, expected_kind="withdraw")


def suspend_address(
    *, request: OperationRequest, policy: OperationsPolicy
) -> OperationReceipt:
    return _unsupported(request=request, policy=policy, expected_kind="suspend_address")
