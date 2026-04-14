from __future__ import annotations

from pathlib import Path

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
def test_should_serve_creates_real_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Uses real create_mcp_server, only patches mcp.run() to prevent blocking."""
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text(f"""\
[skills]
paths = ["{FIXTURES}"]
""")
    monkeypatch.chdir(tmp_path)

    run_called_with: list[dict] = []

    def fake_run(self: object, **kwargs: object) -> None:
        run_called_with.append(kwargs)

    monkeypatch.setattr("mcp.server.fastmcp.FastMCP.run", fake_run)

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0
    assert len(run_called_with) == 1
    assert run_called_with[0].get("transport") == "stdio"
