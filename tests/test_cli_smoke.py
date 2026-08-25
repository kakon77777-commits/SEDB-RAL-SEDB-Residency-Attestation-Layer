import pytest

from sedb_ral import __version__
from sedb_ral.cli import entrypoint, main


def test_version_is_phase3b_b_candidate_version():
    assert __version__ == "0.5.0b1"


def test_help_exits_zero_and_names_phase3a(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "SEDB-RAL Phase 3A" in capsys.readouterr().out


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.5.0b1"


def test_entrypoint_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["sedb-ral", "--version"])
    with pytest.raises(SystemExit) as exc:
        entrypoint()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.5.0b1"
