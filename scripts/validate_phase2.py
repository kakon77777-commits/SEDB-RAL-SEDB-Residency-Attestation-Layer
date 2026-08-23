from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sedb_ral.canonical import canonical_bytes
from sedb_ral.phase2 import validate_basic_phase2


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the integrated SEDB-RAL Basic Phase 2 gate."
    )
    parser.add_argument("--sedb-archive", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_basic_phase2(ROOT, args.sedb_archive)
    sys.stdout.buffer.write(canonical_bytes(report.as_json()) + b"\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
