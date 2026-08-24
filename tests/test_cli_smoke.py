import pytest

from sedb_ral import __version__
from sedb_ral.cli import entrypoint, main


def test_version_is_basic_phase2_version():
    assert __version__ == "0.2.1"


def test_help_exits_zero_and_names_basic_phase2(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "SEDB-RAL Basic Phase 2" in capsys.readouterr().out


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.2.1"


def test_entrypoint_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["sedb-ral", "--version"])
    with pytest.raises(SystemExit) as exc:
        entrypoint()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.2.1"
