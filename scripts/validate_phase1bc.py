from __future__ import annotations

import sys
from pathlib import Path

from sedb_ral.canonical import canonical_bytes
from sedb_ral.phase1bc import validate_phase1bc


def main() -> int:
    report = validate_phase1bc(Path(__file__).parents[1])
    sys.stdout.buffer.write(canonical_bytes(report.as_json()) + b"\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
