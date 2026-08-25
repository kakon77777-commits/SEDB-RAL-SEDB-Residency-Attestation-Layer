from __future__ import annotations

import json
from pathlib import Path

import pytest
from phase3a_operations_helpers import (
    digest,
    initialized_operations_workspace,
    synthetic_registry_status,
    valid_intake,
    valid_operation_request,
    valid_operator_observation,
)
from test_phase3_registration_admission import VERIFIED, authority_for
from test_phase3_registration_prepare import (
    IDS,
    valid_claim,
    valid_host_observation,
)

from sedb_ral.application import authority_digest
from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import read_verified_events, verify_ledger
from sedb_ral.operations.engine import (
    PlannedOperation,
    RegistrarOperationsEngine,
)
from sedb_ral.operations.models import (
    OperationRequest,
    OperatorObservation,
    RegistrarIntake,
)
from sedb_ral.operations.store import OperationsStore
from sedb_ral.projection import project_events

ROOT = Path(__file__).parents[1]
CTCL = json.loads(
    (ROOT / "fixtures/ctcl/registered-anchor.json").read_text(encoding="utf-8")
)


def engine_fixture(tmp_path):
    workspace = initialized_operations_workspace(tmp_path)
    store = OperationsStore(workspace)
    status = synthetic_registry_status()
    mutable_status = dict(status)
    engine = RegistrarOperationsEngine(
        workspace=workspace,
        store=store,
        ledger_root=tmp_path / "canonical-ledger",
        registry_status_provider=lambda: dict(mutable_status),
    )
    claim = valid_claim()
    host = valid_host_observation()
    intake = RegistrarIntake.from_dict(
        valid_intake(
            claim_digest=sha256_ref(claim),
            host_observation_digest=sha256_ref(host),
            durable_handoff_ref=None,
            durable_handoff_digest=None,
        )
    )
    store.submit_intake(intake)
    observation = OperatorObservation.from_dict(valid_operator_observation())
    prepare_request = OperationRequest.from_dict(
        valid_operation_request(
            operation_id="operation:prepare-alpha",
            operation_kind="prepare",
            intake_digest=intake.digest,
            application_digest=None,
            target_ref=None,
            authority_artifact_ref=None,
            authority_artifact_digest=None,
            expected_ledger_head=None,
            checkpoint_evidence_ref=None,
            checkpoint_evidence_digest=None,
            foreign_evidence_pins=[],
        )
    )
    store.submit_request(prepare_request)
    return (
        engine,
        store,
        mutable_status,
        claim,
        host,
        intake,
        observation,
        prepare_request,
    )


def planned_fixture(tmp_path):
    (
        engine,
        store,
        mutable_status,
        claim,
        host,
        intake,
        observation,
        _,
    ) = engine_fixture(tmp_path)
    prepared = engine.prepare("operation:prepare-alpha", claim, host, IDS)
    authority = authority_for(prepared)
    request = OperationRequest.from_dict(
        valid_operation_request(
            operation_id="operation:execute-alpha",
            operation_kind="execute",
            intake_digest=intake.digest,
            application_digest=prepared.application_digest,
            target_ref=prepared.application["claimed_resident_id"],
            authority_artifact_ref=authority["authority_id"],
            authority_artifact_digest=authority_digest(authority),
            expected_ledger_head="GENESIS",
            checkpoint_evidence_ref="checkpoint:synthetic-alpha",
            checkpoint_evidence_digest=digest("7"),
            foreign_evidence_pins=[],
        )
    )
    store.submit_request(request)
    plan = engine.plan(
        request.to_dict()["operation_id"],
        authority=authority,
        ctcl_receipt=CTCL,
        verified_attestation_refs=VERIFIED,
    )
    return (
        engine,
        store,
        mutable_status,
        prepared,
        authority,
        request,
        observation,
        plan,
    )


def test_inspect_is_read_only_and_prepare_is_digest_bound(tmp_path):
    engine, _, _, claim, host, _, _, request = engine_fixture(tmp_path)
    before = {
        path.relative_to(engine.workspace.root).as_posix(): path.read_bytes()
        for path in engine.workspace.root.rglob("*")
        if path.is_file()
    }

    status = engine.inspect(request.to_dict()["operation_id"])

    assert status["state"] == "received"
    assert before == {
        path.relative_to(engine.workspace.root).as_posix(): path.read_bytes()
        for path in engine.workspace.root.rglob("*")
        if path.is_file()
    }
    prepared = engine.prepare(request.to_dict()["operation_id"], claim, host, IDS)
    assert prepared.application_digest == sha256_ref(prepared.application)
    repeated = engine.prepare(request.to_dict()["operation_id"], claim, host, IDS)
    assert repeated.to_dict() == prepared.to_dict()


def test_plan_uses_existing_phase3a_core_and_writes_no_canonical_ledger(tmp_path):
    engine, _, _, prepared, _, request, _, plan = planned_fixture(tmp_path)

    assert isinstance(plan, PlannedOperation)
    assert plan.operation_id == request.to_dict()["operation_id"]
    assert plan.prepared_digest == prepared.digest
    assert plan.source_head is None
    assert plan.candidate_head is not None
    assert not engine.ledger_root.exists()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("registry", "operations_registry_binding_mismatch"),
        ("checkpoint", "operations_checkpoint_stale"),
        ("authority", "operation_authority_digest_mismatch"),
    ],
)
def test_execute_rechecks_every_gate_before_commit(tmp_path, mutation, code):
    (
        engine,
        _,
        mutable_status,
        _,
        authority,
        request,
        observation,
        plan,
    ) = planned_fixture(tmp_path)
    checkpoint_digest = str(request.to_dict()["checkpoint_evidence_digest"])
    supplied_authority = dict(authority)
    if mutation == "registry":
        mutable_status["manifest_digest"] = digest("f")
    elif mutation == "checkpoint":
        checkpoint_digest = digest("e")
    else:
        supplied_authority["principal_ref"] = "principal:other"

    with pytest.raises(RALValidationError) as caught:
        engine.execute(
            request.to_dict()["operation_id"],
            plan,
            authority=supplied_authority,
            ctcl_receipt=CTCL,
            verified_attestation_refs=VERIFIED,
            operator_observation=observation,
            checkpoint_evidence_digest=checkpoint_digest,
        )

    assert caught.value.code == code
    assert not engine.ledger_root.exists()


def test_execute_commits_synthetic_ledger_and_retry_returns_existing_receipt(
    tmp_path,
):
    (
        engine,
        _,
        _,
        prepared,
        authority,
        request,
        observation,
        plan,
    ) = planned_fixture(tmp_path)
    arguments = {
        "authority": authority,
        "ctcl_receipt": CTCL,
        "verified_attestation_refs": VERIFIED,
        "operator_observation": observation,
        "checkpoint_evidence_digest": request.to_dict()["checkpoint_evidence_digest"],
    }

    first = engine.execute(request.to_dict()["operation_id"], plan, **arguments)
    second = engine.execute(request.to_dict()["operation_id"], plan, **arguments)

    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["outcome"] == "complete"
    verification = verify_ledger(
        engine.ledger_root,
        expected_final_chain_digest=first.to_dict()["post_head"],
    )
    assert verification.valid is True
    events = read_verified_events(engine.ledger_root, str(first.to_dict()["post_head"]))
    projection = project_events(events)
    assert prepared.application["claimed_resident_id"] in projection.residents
    assert first.to_dict()["side_effect_counters"] == {
        "synthetic_registry_writes": len(events),
        "production_registry_writes": 0,
        "private_reads": 0,
        "network_calls": 0,
        "external_sends": 0,
        "fabric_events": 0,
    }
