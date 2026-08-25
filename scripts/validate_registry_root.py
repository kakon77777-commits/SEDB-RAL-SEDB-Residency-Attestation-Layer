from __future__ import annotations

# ruff: noqa: I001 - source checkout path precedes local package imports

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sedb_ral.canonical import canonical_bytes, loads_strict
from sedb_ral.errors import RALValidationError
from sedb_ral.registry_root_acceptance import (
    validate_registry_root,
    verify_production_registry_receipt,
    write_registry_root_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the synthetic P3-4 production-root lifecycle."
    )
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument("--output", type=Path)
    outputs.add_argument("--verify-production-receipt", type=Path)
    args = parser.parse_args()
    if args.verify_production_receipt is not None:
        try:
            value = loads_strict(
                args.verify_production_receipt.read_text(encoding="utf-8")
            )
            if not isinstance(value, dict):
                raise RALValidationError(
                    "production_registry_receipt_invalid",
                    "production receipt must be an object",
                )
            verify_production_registry_receipt(value)
        except (OSError, UnicodeError, ValueError, RALValidationError) as error:
            code = (
                error.code
                if isinstance(error, RALValidationError)
                else "production_registry_receipt_unreadable"
            )
            sys.stdout.buffer.write(
                canonical_bytes(
                    {
                        "schema": (
                            "sedb-ral.production-registry-receipt-"
                            "verification/0.1"
                        ),
                        "valid": False,
                        "error_code": code,
                    }
                )
                + b"\n"
            )
            return 2
        sys.stdout.buffer.write(
            canonical_bytes(
                {
                    "schema": (
                        "sedb-ral.production-registry-receipt-verification/0.1"
                    ),
                    "valid": True,
                }
            )
            + b"\n"
        )
        return 0
    report = validate_registry_root(ROOT)
    write_registry_root_report(report, args.output)
    sys.stdout.buffer.write(canonical_bytes(report.as_json()) + b"\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
