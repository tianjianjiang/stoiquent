"""Integration tests for MCP server creation and tool execution."""
from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.models import AppConfig, ProviderConfig
from stoiquent.skills.mcp_app import (
    get_app_metadata,
    get_app_resource_uri,
    inject_app_meta_into_tools,
    resolve_app_html,
)
from stoiquent.skills.mcp_server import create_mcp_server
from stoiquent.skills.models import MCPAppDef, Skill, SkillMeta

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


def _make_config(skills_dir: str) -> AppConfig:
    return AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": [skills_dir]},
        sandbox={"backend": "none"},
    )


@pytest.mark.integration
def test_should_create_mcp_server_from_fixtures() -> None:
    config = _make_config(str(FIXTURES))
    mcp = create_mcp_server(config)
    tool_names = list(mcp._tool_manager._tools.keys())
    assert "greet" in tool_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_handler_from_fixture_skill() -> None:
    config = _make_config(str(FIXTURES))
    mcp = create_mcp_server(config)
    handler = mcp._tool_manager._tools["greet"].fn
    result = await handler(name="IntegrationTest")
    assert "Hello, IntegrationTest!" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_handler_without_args() -> None:
    config = _make_config(str(FIXTURES))
    mcp = create_mcp_server(config)
    handler = mcp._tool_manager._tools["greet"].fn
    result = await handler()
    assert "Hello, World!" in result


@pytest.mark.integration
def test_should_use_skills_dir_parameter() -> None:
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": []},
        sandbox={"backend": "none"},
    )
    mcp = create_mcp_server(config, skills_dir=str(FIXTURES))
    tool_names = list(mcp._tool_manager._tools.keys())
    assert "greet" in tool_names


@pytest.mark.integration
def test_mcp_app_resource_uri_with_real_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "ui-skill"
    assets_dir = skill_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "app.html").write_text("<html><body>Test App</body></html>")

    skill = Skill(
        meta=SkillMeta(
            name="ui-skill",
            description="Skill with UI",
            mcp_app=MCPAppDef(
                resource="assets/app.html",
                permissions=["clipboard-write"],
            ),
        ),
        path=skill_dir,
        active=True,
    )

    uri = get_app_resource_uri(skill)
    assert uri == "ui://ui-skill/assets/app.html"

    html = resolve_app_html(skill)
    assert html is not None
    assert "Test App" in html.read_text()

    meta = get_app_metadata(skill)
    assert meta is not None
    assert meta["ui"]["mimeType"] == "text/html;profile=mcp-app"

    tools = [{"type": "function", "function": {"name": "test_tool"}}]
    injected = inject_app_meta_into_tools(tools, skill)
    assert len(injected) == 1
    assert "_meta" in injected[0]
    assert injected[0]["_meta"]["ui"]["resourceUri"] == "ui://ui-skill/assets/app.html"


@pytest.mark.integration
def test_mcp_app_returns_none_for_skill_without_app() -> None:
    skill = Skill(
        meta=SkillMeta(name="plain", description="No UI"),
        path=Path("/fake"),
    )
    assert get_app_resource_uri(skill) is None
    assert resolve_app_html(skill) is None
    assert get_app_metadata(skill) is None

    tools = [{"type": "function", "function": {"name": "test"}}]
    result = inject_app_meta_into_tools(tools, skill)
    assert result == tools
