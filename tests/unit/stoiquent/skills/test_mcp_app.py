from __future__ import annotations

from pathlib import Path

from stoiquent.skills.mcp_app import (
    get_app_metadata,
    get_app_resource_uri,
    inject_app_meta_into_tools,
    resolve_app_html,
)
from stoiquent.skills.models import MCPAppDef, Skill, SkillMeta


def _make_skill_with_app(tmp_path: Path) -> Skill:
    skill_dir = tmp_path / "ui-skill"
    assets_dir = skill_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "app.html").write_text("<html><body>App</body></html>")

    return Skill(
        meta=SkillMeta(
            name="ui-skill",
            description="Skill with UI",
            mcp_app=MCPAppDef(
                resource="assets/app.html",
                permissions=["clipboard-write"],
                csp=["https://cdn.jsdelivr.net"],
            ),
        ),
        path=skill_dir,
        active=True,
    )


def _make_skill_without_app() -> Skill:
    return Skill(
        meta=SkillMeta(name="plain", description="No UI"),
        path=Path("/skills/plain"),
    )


def test_should_return_resource_uri(tmp_path: Path) -> None:
    skill = _make_skill_with_app(tmp_path)
    uri = get_app_resource_uri(skill)
    assert uri == "ui://ui-skill/assets/app.html"


def test_should_return_none_for_no_app() -> None:
    skill = _make_skill_without_app()
    assert get_app_resource_uri(skill) is None


def test_should_resolve_app_html(tmp_path: Path) -> None:
    skill = _make_skill_with_app(tmp_path)
    html = resolve_app_html(skill)
    assert html is not None
    assert html.name == "app.html"
    assert html.read_text() == "<html><body>App</body></html>"


def test_should_return_none_for_missing_html(tmp_path: Path) -> None:
    skill = Skill(
        meta=SkillMeta(
            name="broken",
            description="Broken UI",
            mcp_app=MCPAppDef(resource="assets/missing.html"),
        ),
        path=tmp_path,
    )
    assert resolve_app_html(skill) is None


def test_should_return_none_for_no_mcp_app() -> None:
    skill = _make_skill_without_app()
    assert resolve_app_html(skill) is None


def test_should_get_app_metadata(tmp_path: Path) -> None:
    skill = _make_skill_with_app(tmp_path)
    meta = get_app_metadata(skill)
    assert meta is not None
    assert meta["ui"]["resourceUri"] == "ui://ui-skill/assets/app.html"
    assert meta["ui"]["mimeType"] == "text/html;profile=mcp-app"
    assert "clipboard-write" in meta["ui"]["permissions"]


def test_should_return_none_metadata_for_no_app() -> None:
    skill = _make_skill_without_app()
    assert get_app_metadata(skill) is None


def test_should_inject_meta_into_tools(tmp_path: Path) -> None:
    skill = _make_skill_with_app(tmp_path)
    tools = [
        {"type": "function", "function": {"name": "tool1"}},
        {"type": "function", "function": {"name": "tool2"}},
    ]
    result = inject_app_meta_into_tools(tools, skill)
    assert len(result) == 2
    for tool in result:
        assert "_meta" in tool
        assert tool["_meta"]["ui"]["resourceUri"] == "ui://ui-skill/assets/app.html"


def test_should_not_inject_meta_for_no_app() -> None:
    skill = _make_skill_without_app()
    tools = [{"type": "function", "function": {"name": "tool1"}}]
    result = inject_app_meta_into_tools(tools, skill)
    assert result == tools
    assert "_meta" not in result[0]
