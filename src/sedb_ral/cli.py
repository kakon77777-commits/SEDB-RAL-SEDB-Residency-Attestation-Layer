from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sedb-ral",
        description="SEDB-RAL Phase 1A deterministic core",
    )
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(__version__)
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
