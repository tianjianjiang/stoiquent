from __future__ import annotations

import pytest
from click.testing import CliRunner

from stoiquent.cli import main


@pytest.mark.integration
def test_should_show_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Stoiquent" in result.output
    assert "run" in result.output
    assert "serve" in result.output
    assert "list-skills" in result.output


@pytest.mark.integration
def test_should_list_skills_or_show_empty() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["list-skills"])
    assert result.exit_code == 0
    assert "No skills found" in result.output or ":" in result.output


@pytest.mark.integration
def test_should_show_serve_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "MCP server" in result.output or "skills" in result.output


@pytest.mark.integration
def test_should_show_run_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "NiceGUI" in result.output or "mode" in result.output


@pytest.mark.integration
def test_should_show_list_skills_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["list-skills", "--help"])
    assert result.exit_code == 0
    assert "discovered" in result.output.lower() or "skills" in result.output.lower()
