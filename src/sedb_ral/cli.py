from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .canonical import canonical_bytes, loads_strict
from .contracts import validate_contract
from .errors import RALValidationError
from .identifier import evaluate_identifier_fixture
from .ledger import LedgerStatus, verify_ledger
from .phase1a import validate_phase1a


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
    return parser


def _print_json(value: object) -> None:
    sys.stdout.buffer.write(canonical_bytes(value) + b"\n")


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


def entrypoint() -> None:
    raise SystemExit(main())
