from __future__ import annotations

import os

import pytest

from sedb_ral.production_operations_recovery import _copy_file_new
from sedb_ral.registry_root import registry_root_status
from test_production_operations_layout import published_storage


def make_hardlink(source, target):
    try:
        os.link(source, target)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")


def test_rehearsal_hardlink_does_not_invalidate_canonical_registry_status(
    published_storage,
):
    rehearsal = published_storage.final / "rehearsals/link-control"
    rehearsal.mkdir()
    source = rehearsal / "source.json"
    alias = rehearsal / "alias.json"
    source.write_text("{}", encoding="utf-8")
    make_hardlink(source, alias)

    status = registry_root_status(storage=published_storage)

    assert status["verified"] is True
    assert status["extensions_status"] == "absent"


def test_versioned_recovery_copies_hardlinked_source_by_value(tmp_path):
    source = tmp_path / "source.json"
    alias = tmp_path / "alias.json"
    destination = tmp_path / "copied.json"
    source.write_text('{"value":1}', encoding="utf-8")
    make_hardlink(source, alias)

    _copy_file_new(source, destination)

    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_nlink == 1
