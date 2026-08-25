from __future__ import annotations

import os
from pathlib import Path

import pytest

import sedb_ral.registry_root as registry_root
from sedb_ral.registry_root import _has_multiple_hardlinks


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows hard-link probe")


def make_hardlink(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")


def test_real_two_name_hardlink_is_detected(tmp_path):
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    source.write_text("{}", encoding="utf-8")
    make_hardlink(source, target)

    assert _has_multiple_hardlinks(source) is True


def test_windows_name_enumeration_overrides_false_positive_nlink(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    source.write_text("{}", encoding="utf-8")
    make_hardlink(source, target)
    assert source.stat().st_nlink > 1
    monkeypatch.setattr(
        registry_root,
        "_windows_hardlink_names",
        lambda _path: (str(source),),
    )

    assert _has_multiple_hardlinks(source) is False


def test_transient_second_link_name_must_repeat_before_rejection(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    source.write_text("{}", encoding="utf-8")
    make_hardlink(source, target)
    observations = iter(
        (("source", "transient-copy"),) * 5 + (("source",),)
    )
    monkeypatch.setattr(
        registry_root,
        "_windows_hardlink_names",
        lambda _path: next(observations),
    )

    assert _has_multiple_hardlinks(source) is False


def test_regular_file_has_one_windows_link_name(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")

    assert len(registry_root._windows_hardlink_names(source)) == 1
    assert _has_multiple_hardlinks(source) is False
