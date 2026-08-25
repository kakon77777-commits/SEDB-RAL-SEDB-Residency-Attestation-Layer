from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from sedb_ral.canonical import canonical_bytes
from sedb_ral.phase3a import validate_phase3a, write_phase3a_report

ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the synthetic/local SEDB-RAL Phase 3A gate."
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="sedb-ral-phase3a-script-") as name:
        report = validate_phase3a(ROOT, output_root=Path(name))
    write_phase3a_report(report, args.output)
    sys.stdout.buffer.write(canonical_bytes(report.as_json()) + b"\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
