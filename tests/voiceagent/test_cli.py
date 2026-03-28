"""Tests for CLI entry point."""
from click.testing import CliRunner

from voiceagent.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Voice Agent" in result.output


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_serve_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--voice" in result.output
    assert "--port" in result.output
    assert "--host" in result.output
    assert "boris" in result.output


def test_talk_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["talk", "--help"])
    assert result.exit_code == 0
    assert "--voice" in result.output
    assert "boris" in result.output


def test_cli_unknown_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["nonexistent"])
    assert result.exit_code != 0
