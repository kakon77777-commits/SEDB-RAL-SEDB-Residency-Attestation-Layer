from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from . import __version__
from .adapters.codex_queue import normalize_codex_queue
from .application import application_digest as digest_application
from .application import evaluate_application
from .canonical import canonical_bytes, loads_strict
from .contracts import validate_contract
from .delivery import reconstruct_delivery
from .errors import RALValidationError
from .explain import explain_claim
from .identifier import evaluate_identifier_fixture
from .ledger import LedgerStatus, read_verified_events, verify_ledger
from .limen_public_view import build_limen_public_view
from .operations.cli import add_operations_parser, handle_operations
from .phase1a import validate_phase1a
from .phase1bc import validate_phase1bc
from .phase2 import validate_basic_phase2
from .projection import project_events
from .production_operations_contracts import (
    default_dormant_policy,
    plan_production_operations_extension,
)
from .production_operations_acceptance import (
    validate_production_operations,
    write_production_operations_report,
)
from .production_operations_layout import (
    prepare_production_operations_candidate,
    verify_production_operations_candidate,
)
from .registrar import (
    RegistrarAdmissionPlan,
    build_admission_plan,
    commit_admission_plan,
    inspect_registration_prefix,
)
from .registration import (
    PreparedRegistration,
    RegistrationIds,
    prepare_registration,
)
from .registration_admission import RegistrationDecision
from .registry_recovery import (
    create_registry_checkpoint,
    rehearse_registry_restore,
    rehearse_registry_rollback,
)
from .registry_root import (
    RegistryStorage,
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    verify_registry_candidate,
)
from .registry_root_contracts import plan_registry_root
from .sqlite_projection import rebuild_sqlite, table_row_counts


class _CLIUsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CLIUsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="sedb-ral",
        description="SEDB-RAL Phase 3A synthetic/local registrar candidate",
    )
    parser.add_argument("--version", action="store_true")
    commands = parser.add_subparsers(dest="command")
    identifier = commands.add_parser(
        "identifier", help="validate identifier discrimination fixtures"
    )
    identifier_commands = identifier.add_subparsers(dest="identifier_command")
    check = identifier_commands.add_parser(
        "check", help="evaluate one discrimination fixture"
    )
    check.add_argument("file", type=Path)

    canonicalize = commands.add_parser(
        "canonicalize", help="emit strict canonical JSON"
    )
    canonicalize.add_argument("file", type=Path)

    contract = commands.add_parser(
        "contract", help="validate public JSON contracts"
    )
    contract_commands = contract.add_subparsers(dest="contract_command")
    contract_validate = contract_commands.add_parser(
        "validate", help="validate one JSON file against a contract"
    )
    contract_validate.add_argument("contract")
    contract_validate.add_argument("file", type=Path)

    ledger = commands.add_parser("ledger", help="inspect a file ledger")
    ledger_commands = ledger.add_subparsers(dest="ledger_command")
    ledger_verify = ledger_commands.add_parser(
        "verify", help="verify a ledger without mutating it"
    )
    ledger_verify.add_argument("root", type=Path)
    ledger_verify.add_argument("--expected-final-chain-digest")

    phase1a = commands.add_parser(
        "phase1a", help="run the integrated Phase 1A gate"
    )
    phase1a_commands = phase1a.add_subparsers(dest="phase1a_command")
    phase1a_verify = phase1a_commands.add_parser(
        "verify", help="validate Phase 1A repository artifacts"
    )
    phase1a_verify.add_argument("root", type=Path)

    application = commands.add_parser("application", help="inspect an application")
    application_commands = application.add_subparsers(dest="application_command")
    application_check = application_commands.add_parser(
        "check", help="evaluate one application fixture without committing it"
    )
    application_check.add_argument("file", type=Path)
    application_prepare = application_commands.add_parser(
        "prepare", help="prepare an immutable self-registration application"
    )
    application_prepare.add_argument("claim", type=Path)
    application_prepare.add_argument("host_observation", type=Path)
    application_prepare.add_argument("--ids", type=Path)
    application_prepare.add_argument("--output", type=Path)
    application_digest = application_commands.add_parser(
        "digest", help="emit the bound application digest"
    )
    application_digest.add_argument("file", type=Path)
    application_explain = application_commands.add_parser(
        "explain", help="emit a non-authoritative human view"
    )
    application_explain.add_argument("file", type=Path)

    registrar = commands.add_parser(
        "registrar", help="stage or admit an exact registration plan"
    )
    registrar_commands = registrar.add_subparsers(dest="registrar_command")
    registrar_plan = registrar_commands.add_parser(
        "plan", help="stage a candidate without canonical writes"
    )
    _add_registrar_common(registrar_plan)
    registrar_plan.add_argument("--staging-parent", required=True, type=Path)
    registrar_plan.add_argument("--output", type=Path)
    registrar_admit = registrar_commands.add_parser(
        "admit", help="commit an exact staged plan"
    )
    registrar_admit.add_argument("plan", type=Path)
    _add_registrar_common(registrar_admit)
    registrar_admit.add_argument("--output", type=Path)
    registrar_status = registrar_commands.add_parser(
        "status", help="inspect one application under an exact ledger head"
    )
    registrar_status.add_argument("application_digest")
    registrar_status.add_argument("--ledger-root", required=True, type=Path)
    registrar_status.add_argument("--expected-head", required=True)

    registry = commands.add_parser(
        "registry", help="read exact-head public registry projections"
    )
    registry_commands = registry.add_subparsers(dest="registry_command")
    registry_root_plan = registry_commands.add_parser(
        "root-plan", help="bind an exact production registry initialization plan"
    )
    registry_root_plan.add_argument("--final-root", required=True)
    registry_root_plan.add_argument("--candidate-id", required=True)
    registry_root_plan.add_argument("--source-commit", required=True)
    registry_root_plan.add_argument("--source-package-version", required=True)
    registry_root_plan.add_argument("--time-ref", required=True)
    registry_root_plan.add_argument("--filesystem", required=True)
    registry_root_plan.add_argument("--volume-identity", required=True)
    registry_root_plan.add_argument("--expected-owner-sid", required=True)
    registry_root_plan.add_argument("--output", type=Path)

    registry_prepare_root = registry_commands.add_parser(
        "prepare-root", help="fill an ACL-protected empty registry candidate"
    )
    _add_registry_candidate_common(registry_prepare_root)
    registry_verify_root = registry_commands.add_parser(
        "verify-root", help="verify an exact empty registry candidate"
    )
    _add_registry_candidate_common(registry_verify_root)
    registry_publish_root = registry_commands.add_parser(
        "publish-root", help="publish a verified candidate by no-replace rename"
    )
    registry_publish_root.add_argument("plan", type=Path)
    registry_publish_root.add_argument("verification", type=Path)
    registry_publish_root.add_argument("--synthetic-storage-root", type=Path)
    registry_publish_root.add_argument("--output", type=Path)
    registry_root_status_parser = registry_commands.add_parser(
        "root-status", help="verify the published empty production registry"
    )
    registry_root_status_parser.add_argument("--expected-plan-digest")
    registry_root_status_parser.add_argument("--synthetic-storage-root", type=Path)
    registry_root_status_parser.add_argument("--output", type=Path)
    registry_checkpoint_root = registry_commands.add_parser(
        "checkpoint-root", help="create a same-volume copied-value checkpoint"
    )
    _add_registry_recovery_common(registry_checkpoint_root)
    registry_checkpoint_root.add_argument("--checkpoint-id", required=True)
    registry_restore = registry_commands.add_parser(
        "rehearse-restore", help="restore a checkpoint into an isolated rehearsal"
    )
    _add_registry_recovery_common(registry_restore)
    registry_restore.add_argument("--checkpoint-root", required=True, type=Path)
    registry_restore.add_argument("--rehearsal-id", required=True)
    registry_rollback = registry_commands.add_parser(
        "rehearse-rollback", help="run corruption and fresh-restore controls"
    )
    _add_registry_recovery_common(registry_rollback)
    registry_rollback.add_argument("--checkpoint-root", required=True, type=Path)
    registry_rollback.add_argument("--rehearsal-id", required=True)
    operations_plan = registry_commands.add_parser(
        "operations-extension-plan",
        help="bind an exact dormant production operations extension plan",
    )
    operations_plan.add_argument("--candidate-id", required=True)
    operations_plan.add_argument("--source-commit", required=True)
    operations_plan.add_argument("--source-package-version", required=True)
    operations_plan.add_argument("--filesystem", required=True)
    operations_plan.add_argument("--volume-identity", required=True)
    operations_plan.add_argument("--expected-owner-sid", required=True)
    operations_plan.add_argument("--acl-observation", required=True, type=Path)
    operations_plan.add_argument("--pre-checkpoint", required=True, type=Path)
    operations_plan.add_argument("--time-ref", required=True)
    operations_plan.add_argument("--synthetic-storage-root", type=Path)
    operations_plan.add_argument("--output", type=Path)
    operations_prepare = registry_commands.add_parser(
        "operations-extension-prepare",
        help="prepare and verify a dormant extension candidate without publishing",
    )
    operations_prepare.add_argument("plan", type=Path)
    operations_prepare.add_argument("authority", type=Path)
    operations_prepare.add_argument("acl_observation", type=Path)
    operations_prepare.add_argument("--synthetic-storage-root", type=Path)
    operations_prepare.add_argument("--output", type=Path)
    operations_status = registry_commands.add_parser(
        "operations-extension-status",
        help="read extension status without mutation",
    )
    operations_status.add_argument("--synthetic-storage-root", type=Path)
    operations_status.add_argument("--output", type=Path)
    operations_acceptance = registry_commands.add_parser(
        "operations-extension-acceptance",
        help="run the deterministic synthetic R3B-B acceptance gate",
    )
    operations_acceptance.add_argument("--repo-root", required=True, type=Path)
    operations_acceptance.add_argument("--output", required=True, type=Path)

    registry_limen_view = registry_commands.add_parser(
        "limen-view", help="export the public LIMEN RAL view"
    )
    registry_limen_view.add_argument(
        "--ledger-root", required=True, type=Path
    )
    registry_limen_view.add_argument("--expected-head", required=True)
    registry_limen_view.add_argument("--output", type=Path)

    project = commands.add_parser("project", help="rebuild a temporary projection")
    project_commands = project.add_subparsers(dest="project_command")
    project_rebuild = project_commands.add_parser(
        "rebuild", help="rebuild a SQLite projection in a temporary directory"
    )
    project_rebuild.add_argument("events", type=Path)

    explain = commands.add_parser("explain", help="explain ledger-derived evidence")
    explain_commands = explain.add_subparsers(dest="explain_command")
    explain_claim_parser = explain_commands.add_parser(
        "claim", help="explain one claim"
    )
    explain_claim_parser.add_argument("events", type=Path)
    explain_claim_parser.add_argument("claim_id")

    diagnose = commands.add_parser("diagnose", help="diagnose read-only observations")
    diagnose_commands = diagnose.add_subparsers(dest="diagnose_command")
    diagnose_delivery = diagnose_commands.add_parser(
        "delivery", help="reconstruct one delivery observation"
    )
    diagnose_delivery.add_argument("file", type=Path)

    phase1bc = commands.add_parser(
        "phase1bc", help="run the integrated Basic Phase 1B/1C gate"
    )
    phase1bc_commands = phase1bc.add_subparsers(dest="phase1bc_command")
    phase1bc_verify = phase1bc_commands.add_parser(
        "verify", help="validate Basic Phase 1B/1C repository artifacts"
    )
    phase1bc_verify.add_argument("root", type=Path)

    phase2 = commands.add_parser(
        "phase2", help="run the integrated Basic Phase 2 compatibility gate"
    )
    phase2_commands = phase2.add_subparsers(dest="phase2_command")
    phase2_verify = phase2_commands.add_parser(
        "verify", help="validate Basic Phase 2 against a pinned SEDB archive"
    )
    phase2_verify.add_argument("root", type=Path)
    phase2_verify.add_argument(
        "--sedb-archive", required=True, type=Path
    )
    add_operations_parser(commands)
    return parser


def _add_registrar_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prepared", type=Path)
    parser.add_argument("decision", type=Path)
    parser.add_argument("authority", type=Path)
    parser.add_argument("--ctcl-receipt", required=True, type=Path)
    parser.add_argument(
        "--verified-attestation-refs", required=True, type=Path
    )
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)


def _add_registry_candidate_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", type=Path)
    parser.add_argument("authority", type=Path)
    parser.add_argument("parent_acl", type=Path)
    parser.add_argument("candidate_acl", type=Path)
    parser.add_argument("--synthetic-storage-root", type=Path)
    parser.add_argument("--output", type=Path)


def _add_registry_recovery_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True)
    parser.add_argument("--authority", required=True, type=Path)
    parser.add_argument("--time-ref", required=True)
    parser.add_argument("--synthetic-storage-root", type=Path)
    parser.add_argument("--output", type=Path)


def _print_json(value: object) -> None:
    sys.stdout.buffer.write(canonical_bytes(_json_value(value)) + b"\n")


def _json_value(value: object) -> object:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _read_json(path: Path) -> object:
    return loads_strict(path.read_text(encoding="utf-8"))


def _object(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RALValidationError(code, "input must be a JSON object")
    return value


def _verified_refs(value: object) -> frozenset[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise RALValidationError(
            "verified_attestation_refs_invalid",
            "verified attestation refs must be a JSON string array",
        )
    if len(value) != len(set(value)):
        raise RALValidationError(
            "verified_attestation_refs_invalid",
            "verified attestation refs must be unique",
        )
    return frozenset(value)


def _expected_head(value: str) -> str | None:
    return None if value == "GENESIS" else value


def _generated_registration_ids(address_count: int) -> RegistrationIds:
    token = lambda: str(uuid4())
    return RegistrationIds(
        prepared_id=f"prepared:{token()}",
        application_id=f"application:{token()}",
        resident_id=f"resident:{token()}",
        instance_id=f"instance:{token()}",
        continuity_line_id=f"line:{token()}",
        address_ids=tuple(
            f"address:codex_thread:{token()}" for _ in range(address_count)
        ),
        claim_ids=(
            f"claim:{token()}",
            f"claim:{token()}",
            f"claim:{token()}",
        ),
    )


def _emit_or_write(value: object, output: Path | None) -> None:
    if output is not None:
        content = canonical_bytes(_json_value(value))
        try:
            with output.open("xb") as stream:
                stream.write(content)
        except FileExistsError as error:
            raise RALValidationError(
                "output_exists", "output path already exists"
            ) from error
        except OSError as error:
            raise RALValidationError(
                "output_unwritable", "output path cannot be written"
            ) from error
    _print_json(value)


def _load_registrar_inputs(args):
    prepared = PreparedRegistration.from_dict(
        _object(_read_json(args.prepared), "prepared_registration_invalid")
    )
    decision = RegistrationDecision.from_dict(
        _object(_read_json(args.decision), "registration_decision_invalid")
    )
    authority = _object(
        _read_json(args.authority), "authority_envelope_invalid"
    )
    ctcl = _object(_read_json(args.ctcl_receipt), "ctcl_receipt_invalid")
    refs = _verified_refs(_read_json(args.verified_attestation_refs))
    return prepared, decision, authority, ctcl, refs


def _registry_storage(args) -> RegistryStorage:
    root = getattr(args, "synthetic_storage_root", None)
    return (
        RegistryStorage.synthetic(root)
        if root is not None
        else RegistryStorage.production()
    )


def _load_registry_candidate_inputs(args):
    return (
        _object(_read_json(args.plan), "registry_root_plan_invalid"),
        _object(_read_json(args.authority), "registry_root_authority_invalid"),
        _object(_read_json(args.parent_acl), "registry_parent_acl_invalid"),
        _object(_read_json(args.candidate_acl), "registry_candidate_acl_invalid"),
    )


def _print_input_error(code: str) -> None:
    _print_json(
        {
            "decision": "error",
            "reason_codes": [code],
            "distinct_residents": 0,
            "distinct_values": 0,
        }
    )


def _print_rejection(code: str) -> None:
    _print_json(
        {
            "decision": "reject",
            "reason_codes": [code],
            "distinct_residents": 0,
            "distinct_values": 0,
        }
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except _CLIUsageError:
        _print_rejection("cli_usage_error")
        return 2
    if args.version:
        print(__version__)
        return 0
    if args.command == "operations":
        return handle_operations(args)
    if args.command == "canonicalize":
        try:
            text = args.file.read_text(encoding="utf-8")
        except UnicodeError:
            _print_input_error("input_not_utf8")
            return 1
        except OSError:
            _print_input_error("input_unreadable")
            return 1
        try:
            value = loads_strict(text)
            _print_json(value)
            return 0
        except json.JSONDecodeError:
            _print_input_error("input_invalid_json")
            return 1
        except RALValidationError as error:
            _print_rejection(error.code)
            return 2
    if args.command == "contract" and args.contract_command == "validate":
        try:
            text = args.file.read_text(encoding="utf-8")
            value = loads_strict(text)
            validate_contract(args.contract, value)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            code = (
                "input_unreadable"
                if isinstance(error, OSError)
                else "input_not_utf8"
                if isinstance(error, UnicodeError)
                else "input_invalid_json"
            )
            _print_json(
                {"contract": args.contract, "valid": False, "error_code": code}
            )
            return 1
        except RALValidationError as error:
            _print_json(
                {
                    "contract": args.contract,
                    "valid": False,
                    "error_code": error.code,
                }
            )
            return 2
        _print_json({"contract": args.contract, "valid": True})
        return 0
    if args.command == "ledger" and args.ledger_command == "verify":
        result = verify_ledger(
            args.root,
            expected_final_chain_digest=args.expected_final_chain_digest,
        )
        _print_json(result.as_json())
        if result.status is LedgerStatus.CHECKPOINT_VERIFIED:
            return 0
        if result.status is LedgerStatus.INVALID:
            return 2
        return 3
    if args.command == "phase1a" and args.phase1a_command == "verify":
        report = validate_phase1a(args.root)
        _print_json(report.as_json())
        return 0 if report.passed else 1
    if args.command == "phase1bc" and args.phase1bc_command == "verify":
        report = validate_phase1bc(args.root)
        _print_json(report.as_json())
        return 0 if report.passed else 1
    if args.command == "phase2" and args.phase2_command == "verify":
        report = validate_basic_phase2(args.root, args.sedb_archive)
        _print_json(report.as_json())
        return 0 if report.passed else 1
    if (
        args.command == "application"
        and args.application_command == "prepare"
    ):
        try:
            claim = _object(
                _read_json(args.claim), "self_application_claim_invalid"
            )
            host = _object(
                _read_json(args.host_observation),
                "registration_host_observation_invalid",
            )
            if args.ids is None:
                addresses = claim.get("desired_addresses")
                address_count = len(addresses) if isinstance(addresses, list) else 0
                ids = _generated_registration_ids(address_count)
            else:
                ids = RegistrationIds.from_dict(
                    _object(
                        _read_json(args.ids), "registration_ids_invalid"
                    )
                )
            prepared = prepare_registration(claim, host, ids)
            _emit_or_write(prepared.to_dict(), args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if (
        args.command == "application"
        and args.application_command == "digest"
    ):
        try:
            value = _object(
                _read_json(args.file), "application_document_invalid"
            )
            if value.get("schema") == "sedb-ral.prepared-registration/0.1":
                digest = PreparedRegistration.from_dict(
                    value
                ).application_digest
            else:
                validate_contract("application.schema.json", value)
                digest = digest_application(value)
            _print_json(
                {
                    "schema": "sedb-ral.application-digest/0.1",
                    "application_digest": digest,
                }
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if (
        args.command == "application"
        and args.application_command == "explain"
    ):
        try:
            prepared = PreparedRegistration.from_dict(
                _object(
                    _read_json(args.file), "prepared_registration_invalid"
                )
            )
            application = prepared.application
            _print_json(
                {
                    "schema": "sedb-ral.application-human-view/0.1",
                    "human_view": True,
                    "canonical_approval_artifact": False,
                    "prepared_digest": prepared.digest,
                    "application_digest": prepared.application_digest,
                    "claimed_resident_id": application[
                        "claimed_resident_id"
                    ],
                    "display_label": application["display_label"],
                    "address_count": len(application["addresses"]),
                    "continuity_claim": prepared.applicant_claim[
                        "continuity_claim"
                    ],
                    "not_claimed": [
                        "registrar_authority",
                        "canonical_commit",
                        "private_access",
                    ],
                }
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registrar" and args.registrar_command == "plan":
        try:
            prepared, decision, authority, ctcl, refs = (
                _load_registrar_inputs(args)
            )
            plan = build_admission_plan(
                args.ledger_root,
                prepared,
                decision,
                authority,
                ctcl,
                expected_head=_expected_head(args.expected_head),
                verified_attestation_refs=refs,
                staging_parent=args.staging_parent,
            )
            _emit_or_write(plan.to_dict(), args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registrar" and args.registrar_command == "admit":
        try:
            prepared, decision, authority, ctcl, refs = (
                _load_registrar_inputs(args)
            )
            plan = RegistrarAdmissionPlan.from_dict(
                _object(_read_json(args.plan), "registrar_plan_invalid")
            )
            if _expected_head(args.expected_head) != plan.source_head:
                raise RALValidationError(
                    "cli_expected_head_plan_mismatch",
                    "CLI expected head differs from the staged plan",
                )
            receipt = commit_admission_plan(
                args.ledger_root,
                plan,
                prepared,
                decision,
                authority,
                ctcl,
                verified_attestation_refs=refs,
            )
            _emit_or_write(receipt.to_dict(), args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registrar" and args.registrar_command == "status":
        try:
            expected_head = _expected_head(args.expected_head)
            if expected_head is None:
                verification = verify_ledger(args.ledger_root)
                events = ()
            else:
                verification = verify_ledger(
                    args.ledger_root,
                    expected_final_chain_digest=expected_head,
                )
                if not verification.valid:
                    code = (
                        verification.error_codes[0]
                        if verification.error_codes
                        else "checkpoint_required"
                    )
                    raise RALValidationError(
                        code, "registrar status requires an exact head"
                    )
                events = read_verified_events(
                    args.ledger_root, expected_head
                )
            registration_status = inspect_registration_prefix(
                events, args.application_digest
            )
            _print_json(
                {
                    "schema": "sedb-ral.registrar-status/0.1",
                    "checkpoint_verified": verification.valid,
                    "ledger_status": verification.status.value,
                    "event_count": verification.event_count,
                    "final_head": verification.final_chain_digest,
                    "application_digest": args.application_digest,
                    "registration_status": registration_status,
                    "mutated": False,
                }
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "root-plan":
        try:
            plan = plan_registry_root(
                final_root=args.final_root,
                candidate_id=args.candidate_id,
                source_commit=args.source_commit,
                source_package_version=args.source_package_version,
                time_ref=args.time_ref,
                filesystem=args.filesystem,
                volume_identity=args.volume_identity,
                expected_owner_sid=args.expected_owner_sid,
            )
            _emit_or_write(plan, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command in {
        "prepare-root",
        "verify-root",
    }:
        try:
            plan, authority, parent_acl, candidate_acl = (
                _load_registry_candidate_inputs(args)
            )
            storage = _registry_storage(args)
            if args.registry_command == "prepare-root":
                result = prepare_registry_candidate(
                    plan,
                    authority,
                    parent_acl,
                    candidate_acl,
                    storage=storage,
                )
            else:
                result = verify_registry_candidate(
                    plan,
                    authority,
                    parent_acl,
                    candidate_acl,
                    storage=storage,
                )
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "publish-root":
        try:
            plan = _object(_read_json(args.plan), "registry_root_plan_invalid")
            verification = _object(
                _read_json(args.verification),
                "registry_candidate_verification_invalid",
            )
            result = publish_registry_candidate(
                plan, verification, storage=_registry_storage(args)
            )
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "root-status":
        try:
            result = registry_root_status(
                expected_plan_digest=args.expected_plan_digest,
                storage=_registry_storage(args),
            )
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "operations-extension-status":
        try:
            result = registry_root_status(storage=_registry_storage(args))
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "operations-extension-plan":
        try:
            acl = _object(
                _read_json(args.acl_observation),
                "registry_acl_observation_invalid",
            )
            checkpoint = _object(
                _read_json(args.pre_checkpoint),
                "versioned_checkpoint_invalid",
            )
            checkpoint_digest = checkpoint.get("checkpoint_digest")
            if not isinstance(checkpoint_digest, str) or not checkpoint_digest:
                raise RALValidationError(
                    "versioned_checkpoint_digest_missing",
                    "pre-activation checkpoint digest is required",
                )
            status = registry_root_status(storage=_registry_storage(args))
            policy = default_dormant_policy()
            result = plan_production_operations_extension(
                registry_status=status,
                candidate_id=args.candidate_id,
                operations_generation=f"operations-generation:{args.candidate_id}",
                policy_digest=str(policy["policy_digest"]),
                source_commit=args.source_commit,
                source_package_version=args.source_package_version,
                filesystem=args.filesystem,
                volume_identity=args.volume_identity,
                expected_owner_sid=args.expected_owner_sid,
                acl_fingerprint=str(acl["acl_fingerprint"]),
                pre_checkpoint_digest=checkpoint_digest,
                time_ref=args.time_ref,
            )
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "operations-extension-prepare":
        try:
            plan = _object(
                _read_json(args.plan), "production_operations_plan_invalid"
            )
            authority = _object(
                _read_json(args.authority),
                "production_operations_authority_invalid",
            )
            acl = _object(
                _read_json(args.acl_observation),
                "registry_acl_observation_invalid",
            )
            storage = _registry_storage(args)
            prepared = prepare_production_operations_candidate(
                plan,
                authority,
                acl,
                default_dormant_policy(),
                storage=storage,
            )
            result = verify_production_operations_candidate(
                plan, prepared, storage=storage
            )
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "operations-extension-acceptance":
        try:
            report = validate_production_operations(args.repo_root)
            write_production_operations_report(report, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0 if report.passed else 2
    if args.command == "registry" and args.registry_command in {
        "checkpoint-root",
        "rehearse-restore",
        "rehearse-rollback",
    }:
        try:
            authority = _object(
                _read_json(args.authority), "registry_root_authority_invalid"
            )
            storage = _registry_storage(args)
            if args.registry_command == "checkpoint-root":
                result = create_registry_checkpoint(
                    root=args.root,
                    checkpoint_id=args.checkpoint_id,
                    authority=authority,
                    time_ref=args.time_ref,
                    storage=storage,
                )
            elif args.registry_command == "rehearse-restore":
                result = rehearse_registry_restore(
                    root=args.root,
                    checkpoint_root=args.checkpoint_root,
                    rehearsal_id=args.rehearsal_id,
                    authority=authority,
                    time_ref=args.time_ref,
                    storage=storage,
                )
            else:
                result = rehearse_registry_rollback(
                    root=args.root,
                    checkpoint_root=args.checkpoint_root,
                    rehearsal_id=args.rehearsal_id,
                    authority=authority,
                    time_ref=args.time_ref,
                    storage=storage,
                )
            _emit_or_write(result, args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "registry" and args.registry_command == "limen-view":
        try:
            events = read_verified_events(
                args.ledger_root, args.expected_head
            )
            if not events:
                raise RALValidationError(
                    "external_anchor_mismatch",
                    "public view requires a non-empty exact-head ledger",
                )
            view = build_limen_public_view(
                project_events(events),
                ledger_head=args.expected_head,
                sequence=int(events[-1]["ledger_seq"]),
            )
            _emit_or_write(view.to_dict(), args.output)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RALValidationError,
            KeyError,
            TypeError,
        ) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        return 0
    if args.command == "application" and args.application_command == "check":
        try:
            fixture = _read_json(args.file)
            result = evaluate_application(
                fixture["application"],
                fixture["authorities"],
                # Input authority references are claims, not verification evidence.
                verified_attestation_refs=frozenset(),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError, KeyError, TypeError) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        _print_json(result.as_json())
        return 0 if result.decision == "accept" else 3
    if args.command == "project" and args.project_command == "rebuild":
        try:
            events = _read_json(args.events)
            if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
                raise RALValidationError("events_not_array", "events must be an array of objects")
            with tempfile.TemporaryDirectory(prefix="sedb-ral-cli-") as name:
                path = rebuild_sqlite(events, Path(name) / "ral.sqlite3")
                counts = table_row_counts(path)
        except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError, KeyError, TypeError) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        _print_json(counts)
        return 0
    if args.command == "explain" and args.explain_command == "claim":
        try:
            events = _read_json(args.events)
            if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
                raise RALValidationError("events_not_array", "events must be an array of objects")
            result = explain_claim(events, args.claim_id)
        except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError, KeyError, TypeError) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        _print_json(result.as_json())
        return 0
    if args.command == "diagnose" and args.diagnose_command == "delivery":
        try:
            value = _read_json(args.file)
            if not isinstance(value, dict):
                raise RALValidationError("adapter_observation_not_object", "input must be an object")
            result = reconstruct_delivery((normalize_codex_queue(value),))
        except (OSError, UnicodeError, json.JSONDecodeError, RALValidationError, KeyError, TypeError) as error:
            code = _error_code(error)
            _print_rejection(code)
            return 1 if code.startswith("input_") else 2
        _print_json(asdict(result))
        return 0
    if args.command == "identifier" and args.identifier_command == "check":
        try:
            text = args.file.read_text(encoding="utf-8")
        except UnicodeError:
            _print_input_error("input_not_utf8")
            return 1
        except OSError:
            _print_input_error("input_unreadable")
            return 1
        try:
            value = loads_strict(text)
        except json.JSONDecodeError:
            _print_input_error("input_invalid_json")
            return 1
        except RALValidationError as error:
            _print_rejection(error.code)
            return 2
        try:
            result = evaluate_identifier_fixture(value)
        except RALValidationError as error:
            _print_rejection(error.code)
            return 2
        _print_json(result.as_json())
        if result.decision.value == "admit":
            return 0
        if result.decision.value == "indeterminate":
            return 3
        return 2
    return 0


def _error_code(error: Exception) -> str:
    if isinstance(error, RALValidationError):
        return error.code
    if isinstance(error, json.JSONDecodeError):
        return "input_invalid_json"
    if isinstance(error, UnicodeError):
        return "input_not_utf8"
    if isinstance(error, OSError):
        return "input_unreadable"
    return "input_invalid"


def entrypoint() -> None:
    raise SystemExit(main())
