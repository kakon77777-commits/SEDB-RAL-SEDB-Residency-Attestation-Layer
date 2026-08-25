from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..canonical import canonical_bytes, loads_strict, sha256_ref
from ..errors import RALValidationError
from ..registry_root_contracts import bind_document_digest
from .models import (
    OperationReceipt,
    OperationRequest,
    OperationsPolicy,
    OperatorObservation,
    RegistrarIntake,
)
from .workspace import OperationsWorkspace


@dataclass(frozen=True)
class StoreResult:
    kind: Literal["created", "duplicate", "quarantined"]
    relative_ref: str
    record_digest: str


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    error_code: str | None
    lease_ref: str | None
    lease_digest: str | None


def _token(kind: str, identifier: str) -> str:
    return sha256_ref({"kind": kind, "identifier": identifier}).rsplit(":", 1)[-1][:24]


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(code, "operations record cannot be read") from error
    if not isinstance(value, dict):
        raise RALValidationError(code, "operations record must be an object")
    return value


def _write_new(path: Path, value: dict[str, object]) -> bool:
    try:
        with path.open("xb") as stream:
            stream.write(canonical_bytes(value))
    except FileExistsError:
        return False
    return True


def _verify_bound(value: dict[str, object], field: str, error_code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(error_code, "operations record digest differs")


class OperationsStore:
    def __init__(self, workspace: OperationsWorkspace):
        self.workspace = workspace

    def _quarantine(
        self,
        *,
        kind: str,
        identifier: str,
        existing_digest: str,
        incoming_digest: str,
        error_code: str,
    ) -> StoreResult:
        material = {
            "schema": "sedb-ral.operations-quarantine-observation/0.1",
            "record_kind": kind,
            "record_id": identifier,
            "existing_digest": existing_digest,
            "incoming_digest": incoming_digest,
            "error_code": error_code,
            "operations_generation": self.workspace.manifest.to_dict()[
                "operations_generation"
            ],
            "not_claimed": [
                "source_deleted",
                "conflict_resolved",
                "canonical_commit",
            ],
        }
        value = bind_document_digest(material, "observation_digest")
        suffix = incoming_digest.rsplit(":", 1)[-1][:24]
        path = (
            self.workspace.root
            / "audit"
            / f"quarantine-{kind}-{_token(kind, identifier)}-{suffix}.json"
        )
        _write_new(path, value)
        return StoreResult(
            kind="quarantined",
            relative_ref=path.relative_to(self.workspace.root).as_posix(),
            record_digest=str(value["observation_digest"]),
        )

    def _submit(
        self,
        *,
        directory: str,
        kind: str,
        identifier: str,
        value: dict[str, object],
        digest_field: str,
        conflict_code: str,
    ) -> StoreResult:
        digest = str(value[digest_field])
        path = (
            self.workspace.root / directory / f"{kind}-{_token(kind, identifier)}.json"
        )
        if _write_new(path, value):
            return StoreResult(
                kind="created",
                relative_ref=path.relative_to(self.workspace.root).as_posix(),
                record_digest=digest,
            )
        existing = _read_object(path, f"operations_{kind}_invalid_json")
        existing_digest = str(existing.get(digest_field, ""))
        if existing_digest == digest and canonical_bytes(existing) == canonical_bytes(
            value
        ):
            return StoreResult(
                kind="duplicate",
                relative_ref=path.relative_to(self.workspace.root).as_posix(),
                record_digest=digest,
            )
        return self._quarantine(
            kind=kind,
            identifier=identifier,
            existing_digest=existing_digest,
            incoming_digest=digest,
            error_code=conflict_code,
        )

    def submit_intake(self, intake: RegistrarIntake) -> StoreResult:
        value = intake.to_dict()
        return self._submit(
            directory="inbox",
            kind="intake",
            identifier=str(value["intake_id"]),
            value=value,
            digest_field="intake_digest",
            conflict_code="intake_id_digest_conflict",
        )

    def submit_request(self, request: OperationRequest) -> StoreResult:
        value = request.to_dict()
        return self._submit(
            directory="requests",
            kind="request",
            identifier=str(value["operation_id"]),
            value=value,
            digest_field="operation_digest",
            conflict_code="operation_id_digest_conflict",
        )

    def write_receipt(self, receipt: OperationReceipt) -> StoreResult:
        value = receipt.to_dict()
        return self._submit(
            directory="receipts",
            kind="receipt",
            identifier=str(value["operation_id"]),
            value=value,
            digest_field="receipt_digest",
            conflict_code="operation_receipt_digest_conflict",
        )

    def append_audit(self, value: dict[str, object]) -> StoreResult:
        canonical = loads_strict(canonical_bytes(value).decode("utf-8"))
        if not isinstance(canonical, dict):
            raise RALValidationError(
                "operations_audit_invalid", "audit must remain an object"
            )
        bound = bind_document_digest(canonical, "audit_digest")
        digest = str(bound["audit_digest"])
        path = (
            self.workspace.root
            / "audit"
            / f"audit-{digest.rsplit(':', 1)[-1][:24]}.json"
        )
        created = _write_new(path, bound)
        return StoreResult(
            kind="created" if created else "duplicate",
            relative_ref=path.relative_to(self.workspace.root).as_posix(),
            record_digest=digest,
        )

    def _operation_path(self, directory: str, kind: str, operation_id: str) -> Path:
        return (
            self.workspace.root
            / directory
            / f"{kind}-{_token(kind, operation_id)}.json"
        )

    def status(self, operation_id: str) -> dict[str, object]:
        request_path = self._operation_path("requests", "request", operation_id)
        receipt_path = self._operation_path("receipts", "receipt", operation_id)
        request_digest = None
        receipt_digest = None
        state = "unknown"
        if request_path.is_file():
            request = OperationRequest.from_dict(
                _read_object(request_path, "operations_request_invalid_json")
            )
            request_digest = request.digest
            state = "received"
        if receipt_path.is_file():
            receipt = OperationReceipt.from_dict(
                _read_object(receipt_path, "operations_receipt_invalid_json")
            )
            receipt_digest = receipt.digest
            state = str(receipt.to_dict()["outcome"])
        return {
            "schema": "sedb-ral.operations-status/0.1",
            "operation_id": operation_id,
            "state": state,
            "request_digest": request_digest,
            "receipt_digest": receipt_digest,
            "mutated": False,
        }

    def _active_policy(self) -> OperationsPolicy:
        activations = sorted((self.workspace.root / "active-policy").glob("*.json"))
        if not activations:
            raise RALValidationError(
                "operations_policy_unavailable", "active policy is unavailable"
            )
        activation = _read_object(
            activations[-1], "operations_policy_activation_invalid_json"
        )
        policy_digest = str(activation["policy_digest"])
        for path in (self.workspace.root / "policies").glob("policy-*.json"):
            policy = OperationsPolicy.from_dict(
                _read_object(path, "operations_policy_invalid_json")
            )
            if policy.digest == policy_digest:
                return policy
        raise RALValidationError(
            "operations_policy_unavailable", "active policy bytes are unavailable"
        )

    def acquire_lease(
        self,
        request: OperationRequest,
        observation: OperatorObservation,
    ) -> LeaseResult:
        request_value = request.to_dict()
        observation_value = observation.to_dict()
        if (
            request_value["operator_observation_ref"]
            != observation_value["observation_id"]
            or request_value["operator_observation_digest"] != observation.digest
        ):
            raise RALValidationError(
                "operation_operator_observation_mismatch",
                "request binds another operator observation",
            )
        operation_id = str(request_value["operation_id"])
        policy = self._active_policy().to_dict()
        lease_value = bind_document_digest(
            {
                "schema": "sedb-ral.operations-lease/0.1",
                "operation_id": operation_id,
                "request_digest": request.digest,
                "operator_observation_digest": observation.digest,
                "operations_generation": self.workspace.manifest.to_dict()[
                    "operations_generation"
                ],
                "lease_seconds": policy["lease_seconds"],
                "acquired_time_ref": observation_value["observed_time_ref"],
                "expiry_is_claim_only": True,
                "not_claimed": [
                    "process_alive",
                    "stale_recovery_authority",
                    "canonical_commit",
                ],
            },
            "lease_digest",
        )
        path = self._operation_path("leases", "lease", operation_id)
        if not _write_new(path, lease_value):
            return LeaseResult(
                acquired=False,
                error_code="operation_in_progress",
                lease_ref=path.relative_to(self.workspace.root).as_posix(),
                lease_digest=None,
            )
        return LeaseResult(
            acquired=True,
            error_code=None,
            lease_ref=path.relative_to(self.workspace.root).as_posix(),
            lease_digest=str(lease_value["lease_digest"]),
        )

    def record_lease_release(
        self, request: OperationRequest, lease_digest: str
    ) -> dict[str, object]:
        request_value = request.to_dict()
        operation_id = str(request_value["operation_id"])
        lease_path = self._operation_path("leases", "lease", operation_id)
        lease = _read_object(lease_path, "operations_lease_invalid_json")
        _verify_bound(lease, "lease_digest", "operations_lease_digest_mismatch")
        if (
            lease["lease_digest"] != lease_digest
            or lease["request_digest"] != request.digest
        ):
            raise RALValidationError(
                "operations_lease_mismatch", "lease binds another request"
            )
        release = bind_document_digest(
            {
                "schema": "sedb-ral.operations-lease-release/0.1",
                "operation_id": operation_id,
                "request_digest": request.digest,
                "lease_digest": lease_digest,
                "operations_generation": self.workspace.manifest.to_dict()[
                    "operations_generation"
                ],
                "released_time_ref": request_value["created_time_ref"],
                "lease_file_deleted": False,
                "not_claimed": [
                    "canonical_commit",
                    "process_terminated",
                    "stale_recovery_authority",
                ],
            },
            "release_digest",
        )
        suffix = lease_digest.rsplit(":", 1)[-1][:24]
        path = (
            self.workspace.root
            / "audit"
            / f"lease-release-{_token('lease', operation_id)}-{suffix}.json"
        )
        _write_new(path, release)
        return release
