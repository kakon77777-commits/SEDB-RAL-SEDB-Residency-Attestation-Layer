from __future__ import annotations

from pathlib import Path

from sedb_ral.incidents import load_incidents, render_incidents


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = root / "corpus" / "incidents.jsonl"
    target = root / "corpus" / "incidents.md"
    target.write_text(
        render_incidents(load_incidents(source)),
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
