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
from .phase1a import validate_phase1a
from .phase1bc import validate_phase1bc
from .phase2 import validate_basic_phase2
from .projection import project_events
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
