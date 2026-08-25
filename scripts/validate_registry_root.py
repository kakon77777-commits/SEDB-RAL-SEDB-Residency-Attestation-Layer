from __future__ import annotations

# ruff: noqa: I001 - source checkout path precedes local package imports

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sedb_ral.canonical import canonical_bytes
from sedb_ral.registry_root_acceptance import (
    validate_registry_root,
    write_registry_root_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the synthetic P3-4 production-root lifecycle."
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = validate_registry_root(ROOT)
    write_registry_root_report(report, args.output)
    sys.stdout.buffer.write(canonical_bytes(report.as_json()) + b"\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
