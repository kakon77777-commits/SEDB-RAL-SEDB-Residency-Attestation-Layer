from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from sedb_ral.registration_wave_acceptance import (
    validate_registration_wave,
    write_registration_wave_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="run the deterministic synthetic R3B-C Wave 1 gate"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sedb-ral-r3bc-") as name:
        report = validate_registration_wave(Path(name))
    write_registration_wave_report(report, args.output)
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
