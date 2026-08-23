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


def verify_manifest_at_commit(
    root: Path,
    manifest: str,
    commit: str,
) -> tuple[str, ...]:
    errors: list[str] = []
    entries: dict[str, str] = {}
    for line in manifest.splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError:
            errors.append("manifest_line_invalid")
            continue
        if len(digest) != 64 or relative in entries:
            errors.append("manifest_line_invalid")
            continue
        entries[relative] = digest

    try:
        tree_output = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", commit],
            cwd=root,
            text=True,
            encoding="utf-8",
        )
        tree_paths = set(tree_output.splitlines())
    except subprocess.CalledProcessError:
        return ("checkpoint_commit_unavailable",)

    expected_paths = tree_paths - {"SHA256SUMS.txt"}
    if set(entries) != expected_paths:
        errors.append("manifest_path_set_mismatch")

    for relative, expected in sorted(entries.items()):
        try:
            data = subprocess.check_output(
                ["git", "show", f"{commit}:{relative}"],
                cwd=root,
            )
        except subprocess.CalledProcessError:
            errors.append(f"manifest_blob_missing:{relative}")
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            errors.append(f"manifest_digest_mismatch:{relative}")
    return tuple(sorted(set(errors)))


if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[1]
    (repository / "SHA256SUMS.txt").write_text(
        build_manifest(repository),
        encoding="utf-8",
        newline="\n",
    )
