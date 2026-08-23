import pytest

from sedb_ral import __version__
from sedb_ral.cli import main


def test_version_is_phase_1a_version():
    assert __version__ == "0.1.0"


def test_help_exits_zero_and_names_phase_1a(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "SEDB-RAL Phase 1A" in capsys.readouterr().out


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
