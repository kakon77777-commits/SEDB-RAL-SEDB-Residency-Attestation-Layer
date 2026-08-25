from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sedb_ral.canonical import canonical_bytes
from sedb_ral.phase3a_operations import (
    validate_phase3a_operations,
    write_operations_report,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = validate_phase3a_operations(ROOT)
    write_operations_report(report, args.output)
    sys.stdout.buffer.write(canonical_bytes(report.to_dict()) + b"\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
