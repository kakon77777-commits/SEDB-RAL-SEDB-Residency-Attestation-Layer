from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

FILENAME = "SEDB-v0.4B-local.zip"
ENVIRONMENT_KEY = "SEDB_V04B_ARCHIVE"


def locate_sedb_v04b_archive(
    *,
    explicit: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    start: str | Path | None = None,
) -> Path | None:
    environment = os.environ if environ is None else environ
    if explicit is not None:
        return Path(explicit).resolve()
    configured = environment.get(ENVIRONMENT_KEY)
    if configured:
        return Path(configured).resolve()

    origin = Path.cwd() if start is None else Path(start)
    resolved = origin.resolve()
    for candidate in (resolved, *resolved.parents):
        if candidate.name.casefold() != "sedb-ral":
            continue
        archive = candidate.parent / "SEDB" / "releases" / FILENAME
        return archive.resolve() if archive.is_file() else None
    return None


def require_sedb_v04b_archive(path: Path | None) -> Path:
    if path is None or not path.is_file():
        pytest.skip("archive_unavailable")
    return path
