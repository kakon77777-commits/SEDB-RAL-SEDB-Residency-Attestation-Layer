from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .canonical import canonical_bytes, loads_strict
from .contracts import validate_contract
from .delivery import reconstruct_delivery
from .errors import RALValidationError
from .explain import explain_claim
from .identifier import evaluate_identifier_fixture
from .ledger import LedgerStatus, verify_ledger
from .phase1a import validate_phase1a
from .phase1bc import validate_phase1bc
from .sqlite_projection import rebuild_sqlite, table_row_counts
from .adapters.codex_queue import normalize_codex_queue
from .application import evaluate_application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sedb-ral",
        description="SEDB-RAL Phase 1A deterministic core",
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
    return parser


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
    args = build_parser().parse_args(argv)
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
