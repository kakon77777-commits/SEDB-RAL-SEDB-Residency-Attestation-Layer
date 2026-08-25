from __future__ import annotations

import json

from phase3a_operations_helpers import (
    initialized_operations_workspace,
    valid_intake,
    valid_operation_receipt,
    valid_operation_request,
)

from sedb_ral.operations.models import (
    OperationReceipt,
    OperationRequest,
    RegistrarIntake,
)
from sedb_ral.operations.store import OperationsStore


def test_same_intake_is_idempotent_and_conflicting_intake_is_quarantined(
    tmp_path,
):
    store = OperationsStore(initialized_operations_workspace(tmp_path))
    first = store.submit_intake(RegistrarIntake.from_dict(valid_intake()))
    same = store.submit_intake(RegistrarIntake.from_dict(valid_intake()))
    conflict = store.submit_intake(
        RegistrarIntake.from_dict(valid_intake(claim_digest="sha256:other-claim"))
    )

    assert (first.kind, same.kind, conflict.kind) == (
        "created",
        "duplicate",
        "quarantined",
    )
    assert len(tuple((store.workspace.root / "inbox").glob("*.json"))) == 1
    quarantine = tuple(
        (store.workspace.root / "audit").glob("quarantine-intake-*.json")
    )
    assert len(quarantine) == 1
    value = json.loads(quarantine[0].read_text(encoding="utf-8"))
    assert value["error_code"] == "intake_id_digest_conflict"


def test_same_operation_request_is_duplicate_and_conflict_is_quarantined(
    tmp_path,
):
    store = OperationsStore(initialized_operations_workspace(tmp_path))
    first = store.submit_request(OperationRequest.from_dict(valid_operation_request()))
    same = store.submit_request(OperationRequest.from_dict(valid_operation_request()))
    conflict = store.submit_request(
        OperationRequest.from_dict(
            valid_operation_request(application_digest="sha256:other-app")
        )
    )

    assert (first.kind, same.kind, conflict.kind) == (
        "created",
        "duplicate",
        "quarantined",
    )
    assert len(tuple((store.workspace.root / "requests").glob("*.json"))) == 1


def test_receipt_is_create_new_and_status_becomes_complete(tmp_path):
    store = OperationsStore(initialized_operations_workspace(tmp_path))
    request = OperationRequest.from_dict(valid_operation_request())
    receipt = OperationReceipt.from_dict(valid_operation_receipt())
    store.submit_request(request)

    first = store.write_receipt(receipt)
    same = store.write_receipt(receipt)
    status = store.status(request.to_dict()["operation_id"])

    assert (first.kind, same.kind) == ("created", "duplicate")
    assert status["state"] == "complete"
    assert status["request_digest"] == request.digest
    assert status["receipt_digest"] == receipt.digest


def test_append_audit_is_digest_idempotent(tmp_path):
    store = OperationsStore(initialized_operations_workspace(tmp_path))
    audit = {
        "schema": "sedb-ral.operations-audit/0.1",
        "operation_id": "operation:test",
        "audit_kind": "inspected",
        "time_ref": "time:synthetic",
        "not_claimed": ["authority", "canonical_commit"],
    }

    first = store.append_audit(audit)
    same = store.append_audit(audit)

    assert (first.kind, same.kind) == ("created", "duplicate")
    assert first.record_digest == same.record_digest
    assert len(tuple((store.workspace.root / "audit").glob("audit-*.json"))) == 1
