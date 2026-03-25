"""Tests for the hedge serve CLI command."""

from click.testing import CliRunner

from src.cli.hedge import cli


def test_serve_help():
    """hedge serve --help renders correctly."""
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "daemon scheduler" in result.output.lower()
    assert "--dry-run" in result.output
    assert "--drift-threshold" in result.output
    assert "--pods" in result.output
    assert "Phase 1" in result.output
    assert "Phase 2" in result.output


def test_serve_shows_in_main_help():
    """hedge serve appears in the main command group help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
