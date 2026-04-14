from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from stoiquent.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


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


@pytest.mark.integration
def test_should_list_skills_from_fixture_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text(f"""\
[skills]
paths = ["{FIXTURES}"]
""")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["list-skills"])
    assert result.exit_code == 0
    assert "hello-world" in result.output


@pytest.mark.integration
def test_should_serve_with_mock_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text(f"""\
[skills]
paths = ["{FIXTURES}"]
""")
    monkeypatch.chdir(tmp_path)

    with patch("stoiquent.skills.mcp_server.FastMCP") as mock_fastmcp:
        mock_instance = mock_fastmcp.return_value
        mock_instance._tool_manager._tools = {}
        mock_instance.tool.return_value = lambda f: f

        runner = CliRunner()
        result = runner.invoke(main, ["serve"])
        assert result.exit_code == 0
        mock_instance.run.assert_called_once_with(transport="stdio")
