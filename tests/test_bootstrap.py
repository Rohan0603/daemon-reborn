"""Smoke tests for the clean-slate project bootstrap."""

import sys

import pytest

from daemon_reborn import __version__
from daemon_reborn.cli import main


def test_cli_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    assert "Daemon Reborn desktop companion bootstrap" in capsys.readouterr().out


def test_domain_import_does_not_load_qt() -> None:
    import daemon_reborn.domain  # noqa: F401

    assert not any(name == "PySide6" or name.startswith("PySide6.") for name in sys.modules)


def test_bootstrap_version_is_set() -> None:
    assert __version__ == "0.1.0"
