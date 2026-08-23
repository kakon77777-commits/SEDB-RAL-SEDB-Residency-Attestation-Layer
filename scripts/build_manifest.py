from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def release_paths(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
        encoding="utf-8",
    )
    return [
        root / relative
        for relative in sorted(line for line in output.splitlines() if line)
        if relative != "SHA256SUMS.txt"
    ]


def build_manifest(root: Path, paths: list[Path] | None = None) -> str:
    selected = release_paths(root) if paths is None else sorted(paths)
    lines = []
    for path in selected:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(root).as_posix()
        lines.append(f"{digest}  {relative}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[1]
    (repository / "SHA256SUMS.txt").write_text(
        build_manifest(repository),
        encoding="utf-8",
        newline="\n",
    )
