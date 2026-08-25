from __future__ import annotations

import argparse
from pathlib import Path

from sedb_ral.production_operations_acceptance import (
    validate_production_operations,
    write_production_operations_report,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    report = validate_production_operations(root)
    write_production_operations_report(report, args.output)
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
