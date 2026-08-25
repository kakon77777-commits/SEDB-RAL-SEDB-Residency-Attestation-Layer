from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..application import authority_digest
from ..canonical import canonical_bytes, loads_strict, sha256_ref
from ..errors import RALValidationError
from ..ledger import read_verified_events
from ..projection import project_events
from ..registrar import (
    RegistrarAdmissionPlan,
    build_admission_plan,
    commit_admission_plan,
)
from ..registration import PreparedRegistration, RegistrationIds, prepare_registration
from ..registration_admission import (
    RegistrationDecision,
    evaluate_prepared_registration,
)
from ..registry_root_contracts import bind_document_digest
from .models import (
    OperationReceipt,
    OperationRequest,
    OperatorObservation,
)
from .store import OperationsStore
from .workspace import OperationsWorkspace, verify_operations_workspace


@dataclass(frozen=True)
class PlannedOperation:
    operation_id: str
    request_digest: str
    prepared_digest: str
    decision_digest: str
    registrar_plan_digest: str
    source_head: str | None
    candidate_head: str
    plan_digest: str

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.planned-operation/0.1",
            "operation_id": self.operation_id,
            "request_digest": self.request_digest,
            "prepared_digest": self.prepared_digest,
            "decision_digest": self.decision_digest,
            "registrar_plan_digest": self.registrar_plan_digest,
            "source_head": self.source_head,
            "candidate_head": self.candidate_head,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._material(), "plan_digest": self.plan_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PlannedOperation:
        expected = {
            "schema",
            "operation_id",
            "request_digest",
            "prepared_digest",
            "decision_digest",
            "registrar_plan_digest",
            "source_head",
            "candidate_head",
            "plan_digest",
        }
        if (
            set(value) != expected
            or value.get("schema") != "sedb-ral.planned-operation/0.1"
        ):
            raise RALValidationError(
                "planned_operation_invalid", "planned operation fields differ"
            )
        scalar = expected - {"source_head"}
        if any(not isinstance(value[name], str) or not value[name] for name in scalar):
            raise RALValidationError(
                "planned_operation_invalid", "planned operation types differ"
            )
        if value["source_head"] is not None and not isinstance(
            value["source_head"], str
        ):
            raise RALValidationError(
                "planned_operation_invalid", "source head type differs"
            )
        plan = cls(
            operation_id=str(value["operation_id"]),
            request_digest=str(value["request_digest"]),
            prepared_digest=str(value["prepared_digest"]),
            decision_digest=str(value["decision_digest"]),
            registrar_plan_digest=str(value["registrar_plan_digest"]),
            source_head=(
                None if value["source_head"] is None else str(value["source_head"])
            ),
            candidate_head=str(value["candidate_head"]),
            plan_digest=str(value["plan_digest"]),
        )
        if sha256_ref(plan._material()) != plan.plan_digest:
            raise RALValidationError(
                "planned_operation_digest_mismatch", "planned operation digest differs"
            )
        return plan


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(code, "operation artifact cannot be read") from error
    if not isinstance(value, dict):
        raise RALValidationError(code, "operation artifact must be an object")
    return value


def _write_idempotent(path: Path, value: Mapping[str, object], code: str) -> None:
    data = canonical_bytes(dict(value))
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise RALValidationError(code, "operation artifact differs")


def _short(value: str) -> str:
    return sha256_ref({"value": value}).rsplit(":", 1)[-1][:24]


class RegistrarOperationsEngine:
    def __init__(
        self,
        *,
        workspace: OperationsWorkspace,
        store: OperationsStore,
        ledger_root: Path,
        registry_status_provider: Callable[[], Mapping[str, object]],
    ):
        self.workspace = workspace
        self.store = store
        self.ledger_root = Path(ledger_root)
        self._registry_status_provider = registry_status_provider

    def inspect(self, operation_id: str) -> dict[str, object]:
        return self.store.status(operation_id)

    def _request(self, operation_id: str) -> OperationRequest:
        return self.store.get_request(operation_id)

    def _prepared_path(self, intake_digest: str) -> Path:
        return (
            self.workspace.root / "staging" / f"prepared-{_short(intake_digest)}.json"
        )

    def _load_prepared(self, intake_digest: str) -> PreparedRegistration:
        path = self._prepared_path(intake_digest)
        if not path.is_file():
            raise RALValidationError(
                "operations_prepared_unavailable", "prepared registration unavailable"
            )
        return PreparedRegistration.from_dict(
            _read_object(path, "operations_prepared_invalid_json")
        )

    def prepare(
        self,
        operation_id: str,
        claim: Mapping[str, object],
        host_observation: Mapping[str, object],
        registration_ids: RegistrationIds,
    ) -> PreparedRegistration:
        request = self._request(operation_id).to_dict()
        if request["operation_kind"] != "prepare" or request["intake_digest"] is None:
            raise RALValidationError(
                "operations_request_kind_mismatch", "prepare request differs"
            )
        intake = self.store.find_intake_by_digest(str(request["intake_digest"]))
        intake_value = intake.to_dict()
        if (
            sha256_ref(dict(claim)) != intake_value["claim_digest"]
            or sha256_ref(dict(host_observation))
            != intake_value["host_observation_digest"]
        ):
            raise RALValidationError(
                "operations_intake_artifact_digest_mismatch",
                "intake artifacts differ from retained digests",
            )
        prepared = prepare_registration(claim, host_observation, registration_ids)
        _write_idempotent(
            self._prepared_path(intake.digest),
            prepared.to_dict(),
            "operations_prepared_conflict",
        )
        return prepared

    def operation_staging_root(self, operation_id: str) -> Path:
        return self.workspace.root / "staging" / f"operation-{_short(operation_id)}"

    def _projection_for_request(self, request: Mapping[str, object]):
        expected = request["expected_ledger_head"]
        if expected in {None, "GENESIS"}:
            return project_events(())
        return project_events(read_verified_events(self.ledger_root, str(expected)))

    def plan(
        self,
        operation_id: str,
        *,
        authority: Mapping[str, object],
        ctcl_receipt: Mapping[str, object],
        verified_attestation_refs: frozenset[str],
    ) -> PlannedOperation:
        request_model = self._request(operation_id)
        request = request_model.to_dict()
        if request["operation_kind"] not in {"plan", "execute"}:
            raise RALValidationError(
                "operations_request_kind_mismatch", "plan request differs"
            )
        intake_digest = request["intake_digest"]
        if not isinstance(intake_digest, str):
            raise RALValidationError(
                "operations_intake_unavailable", "request has no intake"
            )
        prepared = self._load_prepared(intake_digest)
        if request["application_digest"] != prepared.application_digest:
            raise RALValidationError(
                "operation_application_digest_mismatch",
                "request binds another application",
            )
        if request["authority_artifact_digest"] != authority_digest(
            authority
        ) or request["authority_artifact_ref"] != authority.get("authority_id"):
            raise RALValidationError(
                "operation_authority_digest_mismatch", "request binds another authority"
            )
        projection = self._projection_for_request(request)
        decision = evaluate_prepared_registration(
            prepared,
            [authority],
            verified_attestation_refs=verified_attestation_refs,
            projection=projection,
        )
        if decision.decision != "accept":
            code = (
                decision.reason_codes[0]
                if decision.reason_codes
                else "operation_deferred"
            )
            raise RALValidationError(code, "registration decision did not accept")
        expected_head = (
            None
            if request["expected_ledger_head"] == "GENESIS"
            else request["expected_ledger_head"]
        )
        registrar_plan = build_admission_plan(
            self.ledger_root,
            prepared,
            decision,
            authority,
            ctcl_receipt,
            expected_head=expected_head,
            verified_attestation_refs=verified_attestation_refs,
            staging_parent=self.workspace.root / "staging",
        )
        material = {
            "schema": "sedb-ral.planned-operation/0.1",
            "operation_id": operation_id,
            "request_digest": request_model.digest,
            "prepared_digest": prepared.digest,
            "decision_digest": decision.digest,
            "registrar_plan_digest": registrar_plan.digest,
            "source_head": registrar_plan.source_head,
            "candidate_head": registrar_plan.candidate_head,
        }
        planned = PlannedOperation.from_dict(
            {**material, "plan_digest": sha256_ref(material)}
        )
        root = self.operation_staging_root(operation_id)
        root.mkdir(exist_ok=True)
        _write_idempotent(
            root / "prepared.json", prepared.to_dict(), "operations_plan_conflict"
        )
        _write_idempotent(
            root / "decision.json", decision.to_dict(), "operations_plan_conflict"
        )
        _write_idempotent(
            root / "registrar-plan.json",
            registrar_plan.to_dict(),
            "operations_plan_conflict",
        )
        _write_idempotent(
            root / "operations-plan.json",
            planned.to_dict(),
            "operations_plan_conflict",
        )
        return planned

    def execute(
        self,
        operation_id: str,
        plan: PlannedOperation,
        *,
        authority: Mapping[str, object],
        ctcl_receipt: Mapping[str, object],
        verified_attestation_refs: frozenset[str],
        operator_observation: OperatorObservation,
        checkpoint_evidence_digest: str,
    ) -> OperationReceipt:
        existing = self.store.get_receipt(operation_id)
        if existing is not None:
            return existing
        plan = PlannedOperation.from_dict(plan.to_dict())
        request_model = self._request(operation_id)
        request = request_model.to_dict()
        if (
            plan.operation_id != operation_id
            or plan.request_digest != request_model.digest
        ):
            raise RALValidationError(
                "planned_operation_request_mismatch", "plan binds another request"
            )
        status = dict(self._registry_status_provider())
        verify_operations_workspace(
            self.workspace.root,
            expected_generation=str(request["operations_generation"]),
            registry_status=status,
        )
        policy = self.store.active_policy()
        if policy.digest != request["policy_digest"]:
            raise RALValidationError("operations_policy_stale", "active policy changed")
        if request["authority_artifact_digest"] != authority_digest(authority):
            raise RALValidationError(
                "operation_authority_digest_mismatch", "authority changed"
            )
        if request["checkpoint_evidence_digest"] != checkpoint_evidence_digest:
            raise RALValidationError(
                "operations_checkpoint_stale", "checkpoint evidence changed"
            )
        root = self.operation_staging_root(operation_id)
        prepared = PreparedRegistration.from_dict(
            _read_object(root / "prepared.json", "operations_prepared_invalid_json")
        )
        decision = RegistrationDecision.from_dict(
            _read_object(root / "decision.json", "operations_decision_invalid_json")
        )
        registrar_plan = RegistrarAdmissionPlan.from_dict(
            _read_object(root / "registrar-plan.json", "operations_plan_invalid_json")
        )
        if (
            prepared.digest != plan.prepared_digest
            or decision.digest != plan.decision_digest
            or registrar_plan.digest != plan.registrar_plan_digest
        ):
            raise RALValidationError(
                "planned_operation_artifact_mismatch", "plan artifacts changed"
            )
        lease = self.store.acquire_lease(request_model, operator_observation)
        if not lease.acquired:
            raise RALValidationError(
                str(lease.error_code), "operation lease is unavailable"
            )
        committed = commit_admission_plan(
            self.ledger_root,
            registrar_plan,
            prepared,
            decision,
            authority,
            ctcl_receipt,
            verified_attestation_refs=verified_attestation_refs,
        )
        receipt_value = bind_document_digest(
            {
                "schema": "sedb-ral.registrar-operation-receipt/0.1",
                "operation_id": operation_id,
                "request_digest": request_model.digest,
                "policy_digest": policy.digest,
                "operations_generation": request["operations_generation"],
                "registry_id": request["registry_id"],
                "pre_head": committed.source_head,
                "post_head": committed.final_head,
                "outcome": "complete",
                "registrar_receipt_ref": f"registrar-receipt:{_short(operation_id)}",
                "registrar_receipt_digest": sha256_ref(committed.to_dict()),
                "projection_ref": None,
                "projection_digest": committed.projection_digest,
                "error_codes": [],
                "side_effect_counters": {
                    "synthetic_registry_writes": len(committed.event_ids),
                    "production_registry_writes": 0,
                    "private_reads": 0,
                    "network_calls": 0,
                    "external_sends": 0,
                    "fabric_events": 0,
                },
                "completed_time_ref": request["created_time_ref"],
                "not_claimed": [
                    "production_activation",
                    "real_applicant",
                    "private_access",
                    "fabric_adoption",
                ],
            },
            "receipt_digest",
        )
        receipt = OperationReceipt.from_dict(receipt_value)
        result = self.store.write_receipt(receipt)
        if result.kind == "quarantined":
            raise RALValidationError(
                "operation_receipt_digest_conflict", "receipt conflicts"
            )
        self.store.record_lease_release(request_model, str(lease.lease_digest))
        return receipt
