from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..canonical import canonical_bytes, loads_strict
from ..errors import RALValidationError
from .engine import PlannedOperation, RegistrarOperationsEngine
from .models import (
    OperationRequest,
    OperationsManifest,
    OperationsPolicy,
    OperatorObservation,
    RegistrarIntake,
)
from .public_export import export_public
from .store import OperationsStore
from .workspace import (
    OperationsWorkspace,
    initialize_synthetic_workspace,
    verify_operations_workspace,
)


def add_operations_parser(commands) -> None:
    operations = commands.add_parser(
        "operations", help="run synthetic-only registrar operations"
    )
    sub = operations.add_subparsers(dest="operations_command")
    init = sub.add_parser("init-synthetic")
    init.add_argument("plan", type=Path)
    init.add_argument("policy", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("root", type=Path)
    verify.add_argument("--expected-generation", required=True)
    verify.add_argument("--registry-status", required=True, type=Path)
    for name, noun in (("intake-add", "intake"), ("request-add", "request")):
        parser = sub.add_parser(name)
        parser.add_argument(noun, type=Path)
        parser.add_argument("--root", required=True, type=Path)
    plan = sub.add_parser("plan")
    _add_engine_common(plan)
    plan.add_argument("--output", required=True, type=Path)
    execute = sub.add_parser("execute")
    _add_engine_common(execute)
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--operator-observation", required=True, type=Path)
    execute.add_argument("--checkpoint-digest", required=True)
    status = sub.add_parser("status")
    status.add_argument("operation_id")
    status.add_argument("--root", required=True, type=Path)
    export = sub.add_parser("export-public")
    export.add_argument("--ledger-root", required=True, type=Path)
    export.add_argument("--expected-head", required=True)
    export.add_argument("--sequence", required=True, type=int)
    export.add_argument("--output", required=True, type=Path)


def _add_engine_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("operation_id")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--registry-status", required=True, type=Path)
    parser.add_argument("--authority", required=True, type=Path)
    parser.add_argument("--ctcl", required=True, type=Path)
    parser.add_argument("--verified-attestation-refs", required=True, type=Path)


def _read(path: Path) -> object:
    return loads_strict(path.read_text(encoding="utf-8"))


def _object(path: Path, code: str) -> dict[str, object]:
    value = _read(path)
    if not isinstance(value, dict):
        raise RALValidationError(code, "input must be an object")
    return value


def _emit(value: object) -> None:
    sys.stdout.buffer.write(canonical_bytes(value) + b"\n")


def _workspace(root: Path) -> OperationsWorkspace:
    manifest = OperationsManifest.from_dict(
        _object(root / "OPERATIONS-MANIFEST.json", "operations_manifest_invalid")
    )
    return OperationsWorkspace(root=root.resolve(), manifest=manifest)


def _refs(path: Path) -> frozenset[str]:
    value = _read(path)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RALValidationError(
            "verified_attestation_refs_invalid", "refs must be a string array"
        )
    return frozenset(value)


def _engine(args):
    workspace = _workspace(args.root)
    store = OperationsStore(workspace)
    status = _object(args.registry_status, "operations_registry_status_invalid")
    engine = RegistrarOperationsEngine(
        workspace=workspace,
        store=store,
        ledger_root=args.ledger_root,
        registry_status_provider=lambda: dict(status),
    )
    return engine


def handle_operations(args) -> int:
    try:
        command = args.operations_command
        if command == "init-synthetic":
            workspace = initialize_synthetic_workspace(
                _object(args.plan, "operations_workspace_plan_invalid"),
                OperationsPolicy.from_dict(
                    _object(args.policy, "operations_policy_invalid")
                ),
            )
            _emit(
                {
                    "schema": "sedb-ral.operations-init-result/0.1",
                    "initialized": True,
                    "operations_generation": workspace.manifest.to_dict()[
                        "operations_generation"
                    ],
                    "manifest_digest": workspace.manifest.digest,
                }
            )
            return 0
        if command == "verify":
            status = _object(args.registry_status, "operations_registry_status_invalid")
            workspace = verify_operations_workspace(
                args.root,
                expected_generation=args.expected_generation,
                registry_status=status,
            )
            _emit(
                {
                    "schema": "sedb-ral.operations-verification/0.1",
                    "verified": True,
                    "operations_generation": workspace.manifest.to_dict()[
                        "operations_generation"
                    ],
                    "manifest_digest": workspace.manifest.digest,
                }
            )
            return 0
        if command == "intake-add":
            result = OperationsStore(_workspace(args.root)).submit_intake(
                RegistrarIntake.from_dict(
                    _object(args.intake, "registrar_intake_invalid")
                )
            )
            _emit(result.__dict__)
            return 0
        if command == "request-add":
            result = OperationsStore(_workspace(args.root)).submit_request(
                OperationRequest.from_dict(
                    _object(args.request, "operation_request_invalid")
                )
            )
            _emit(result.__dict__)
            return 0
        if command == "status":
            _emit(OperationsStore(_workspace(args.root)).status(args.operation_id))
            return 0
        if command == "export-public":
            _emit(
                export_public(
                    ledger_root=args.ledger_root,
                    expected_head=args.expected_head,
                    sequence=args.sequence,
                    destination=args.output,
                )
            )
            return 0
        if command == "plan":
            engine = _engine(args)
            planned = engine.plan(
                args.operation_id,
                authority=_object(args.authority, "authority_invalid"),
                ctcl_receipt=_object(args.ctcl, "ctcl_invalid"),
                verified_attestation_refs=_refs(args.verified_attestation_refs),
            )
            try:
                with args.output.open("xb") as stream:
                    stream.write(canonical_bytes(planned.to_dict()))
            except FileExistsError as error:
                raise RALValidationError("output_exists", "output exists") from error
            _emit(planned.to_dict())
            return 0
        if command == "execute":
            engine = _engine(args)
            receipt = engine.execute(
                args.operation_id,
                PlannedOperation.from_dict(
                    _object(args.plan, "planned_operation_invalid")
                ),
                authority=_object(args.authority, "authority_invalid"),
                ctcl_receipt=_object(args.ctcl, "ctcl_invalid"),
                verified_attestation_refs=_refs(args.verified_attestation_refs),
                operator_observation=OperatorObservation.from_dict(
                    _object(
                        args.operator_observation,
                        "operator_observation_invalid",
                    )
                ),
                checkpoint_evidence_digest=args.checkpoint_digest,
            )
            _emit(receipt.to_dict())
            return 0
    except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError) as error:
        code = (
            error.code if isinstance(error, RALValidationError) else "input_unreadable"
        )
        _emit({"decision": "reject", "reason_codes": [code]})
        return 2 if isinstance(error, RALValidationError) else 1
    _emit({"decision": "reject", "reason_codes": ["cli_usage_error"]})
    return 2
