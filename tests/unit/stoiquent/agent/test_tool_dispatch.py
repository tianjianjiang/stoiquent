from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.agent.tool_dispatch import dispatch_tool_call
from stoiquent.models import ToolCall
from stoiquent.sandbox.models import SandboxPolicy, SandboxResult
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef


def _make_catalog_with_tool(
    tmp_path: Path, tool_name: str = "greet"
) -> SkillCatalog:
    skill_dir = tmp_path / "hello"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / f"{tool_name}.py").write_text(
        "#!/usr/bin/env python3\nimport sys, json\n"
        "args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}\n"
        "print(f\"Hello, {args.get('name', 'World')}!\")\n"
    )

    skill = Skill(
        meta=SkillMeta(
            name="hello",
            description="Greeting skill",
            tools=[SkillToolDef(name=tool_name, description="Greet")],
        ),
        path=skill_dir,
        active=True,
    )
    return SkillCatalog({"hello": skill})


@pytest.mark.asyncio
async def test_should_dispatch_tool_call(tmp_path: Path) -> None:
    catalog = _make_catalog_with_tool(tmp_path)
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="greet", arguments={"name": "Alice"})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 30.0,
    )
    assert "Hello, Alice!" in result


@pytest.mark.asyncio
async def test_should_return_error_for_unknown_tool() -> None:
    catalog = SkillCatalog()
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="nonexistent", arguments={})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 30.0,
    )
    assert "Error" in result
    assert "nonexistent" in result


@pytest.mark.asyncio
async def test_should_return_error_for_missing_script(tmp_path: Path) -> None:
    skill = Skill(
        meta=SkillMeta(
            name="empty",
            description="No scripts",
            tools=[SkillToolDef(name="missing", description="Missing")],
        ),
        path=tmp_path,
        active=True,
    )
    catalog = SkillCatalog({"empty": skill})
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="missing", arguments={})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 30.0,
    )
    assert "Error" in result
    assert "No script found" in result
