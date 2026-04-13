from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from stoiquent.skills.models import (
    MCPAppDef,
    MCPServerDef,
    Skill,
    SkillMeta,
    SkillToolDef,
)


def test_skill_tool_def_defaults() -> None:
    tool = SkillToolDef(name="greet")
    assert tool.name == "greet"
    assert tool.description == ""
    assert tool.parameters == {}


def test_skill_tool_def_rejects_empty_name() -> None:
    with pytest.raises(ValidationError, match="name"):
        SkillToolDef(name="")


def test_skill_tool_def_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SkillToolDef(name="greet", unknown="field")


def test_mcp_server_def_defaults() -> None:
    server = MCPServerDef(command="npx")
    assert server.command == "npx"
    assert server.args == []
    assert server.env == {}


def test_mcp_server_def_rejects_empty_command() -> None:
    with pytest.raises(ValidationError, match="command"):
        MCPServerDef(command="")


def test_mcp_app_def_defaults() -> None:
    app = MCPAppDef(resource="assets/app.html")
    assert app.resource == "assets/app.html"
    assert app.permissions == []
    assert app.csp == []


def test_mcp_app_def_rejects_empty_resource() -> None:
    with pytest.raises(ValidationError, match="resource"):
        MCPAppDef(resource="")


def test_skill_meta_minimal() -> None:
    meta = SkillMeta(name="hello", description="A greeting skill")
    assert meta.name == "hello"
    assert meta.description == "A greeting skill"
    assert meta.version == ""
    assert meta.tags == []
    assert meta.tools == []
    assert meta.mcp_servers == []
    assert meta.mcp_app is None


def test_skill_meta_rejects_empty_name() -> None:
    with pytest.raises(ValidationError, match="name"):
        SkillMeta(name="", description="valid")


def test_skill_meta_rejects_empty_description() -> None:
    with pytest.raises(ValidationError, match="description"):
        SkillMeta(name="valid", description="")


def test_skill_meta_allows_extra_fields() -> None:
    meta = SkillMeta(
        name="hello", description="desc", custom_field="allowed"
    )
    assert meta.model_extra == {"custom_field": "allowed"}


def test_skill_meta_with_tools() -> None:
    meta = SkillMeta(
        name="calc",
        description="Calculator",
        tools=[{"name": "add", "description": "Add two numbers"}],
    )
    assert len(meta.tools) == 1
    assert meta.tools[0].name == "add"


def test_skill_meta_with_mcp_servers() -> None:
    meta = SkillMeta(
        name="web",
        description="Web skill",
        mcp_servers=[{"command": "node", "args": ["server.js"]}],
    )
    assert len(meta.mcp_servers) == 1
    assert meta.mcp_servers[0].command == "node"


def test_skill_meta_with_mcp_app() -> None:
    meta = SkillMeta(
        name="ui",
        description="UI skill",
        mcp_app={"resource": "assets/app.html", "permissions": ["clipboard-write"]},
    )
    assert meta.mcp_app is not None
    assert meta.mcp_app.resource == "assets/app.html"
    assert meta.mcp_app.permissions == ["clipboard-write"]


def test_skill_defaults() -> None:
    meta = SkillMeta(name="hello", description="desc")
    skill = Skill(meta=meta, path=Path("/skills/hello"))
    assert skill.instructions == ""
    assert skill.active is False
    assert skill.source == "user"


def test_skill_with_all_fields() -> None:
    meta = SkillMeta(name="hello", description="desc")
    skill = Skill(
        meta=meta,
        path=Path("/skills/hello"),
        instructions="# Usage\nRun greet",
        active=True,
        source="project",
    )
    assert skill.active is True
    assert skill.source == "project"
    assert "Usage" in skill.instructions


def test_skill_rejects_invalid_source() -> None:
    meta = SkillMeta(name="hello", description="desc")
    with pytest.raises(ValidationError, match="source"):
        Skill(meta=meta, path=Path("/skills/hello"), source="invalid")
