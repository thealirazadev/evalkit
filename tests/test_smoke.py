"""Scaffold smoke tests: the package imports and exposes its version."""

from click.testing import CliRunner

from evalkit import __version__
from evalkit.cli import cli


def test_version_defined() -> None:
    assert __version__ == "0.1.0"


def test_cli_version_option() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
