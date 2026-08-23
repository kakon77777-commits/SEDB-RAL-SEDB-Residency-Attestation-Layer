from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .canonical import canonical_bytes, loads_strict
from .errors import RALValidationError
from .identifier import evaluate_identifier_fixture


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
    return parser


def _print_json(value: object) -> None:
    print(canonical_bytes(value).decode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "identifier" and args.identifier_command == "check":
        try:
            value = loads_strict(args.file.read_text(encoding="utf-8"))
            result = evaluate_identifier_fixture(value)
        except RALValidationError as error:
            _print_json(
                {
                    "decision": "reject",
                    "reason_codes": [error.code],
                    "distinct_residents": 0,
                    "distinct_values": 0,
                }
            )
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
