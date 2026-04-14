from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.agent.tool_dispatch import dispatch_tool_call
from stoiquent.models import ToolCall
from stoiquent.sandbox.models import SandboxPolicy
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


@pytest.mark.asyncio
async def test_should_return_error_on_timeout(tmp_path: Path) -> None:
    skill_dir = tmp_path / "slow"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "hang.py").write_text(
        "#!/usr/bin/env python3\nimport time; time.sleep(10)\n"
    )
    skill = Skill(
        meta=SkillMeta(
            name="slow",
            description="Slow skill",
            tools=[SkillToolDef(name="hang", description="Hangs")],
        ),
        path=skill_dir,
        active=True,
    )
    catalog = SkillCatalog({"slow": skill})
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="hang", arguments={})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 0.1,
    )
    assert "timed out" in result


@pytest.mark.asyncio
async def test_should_return_error_on_nonzero_exit(tmp_path: Path) -> None:
    skill_dir = tmp_path / "fail"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "fail.py").write_text(
        "#!/usr/bin/env python3\nimport sys; sys.stderr.write('bad input\\n'); sys.exit(1)\n"
    )
    skill = Skill(
        meta=SkillMeta(
            name="fail",
            description="Failing skill",
            tools=[SkillToolDef(name="fail", description="Fails")],
        ),
        path=skill_dir,
        active=True,
    )
    catalog = SkillCatalog({"fail": skill})
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="fail", arguments={})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 30.0,
    )
    assert "Error (exit 1)" in result
    assert "bad input" in result


@pytest.mark.asyncio
async def test_should_dispatch_without_arguments(tmp_path: Path) -> None:
    catalog = _make_catalog_with_tool(tmp_path)
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="greet", arguments={})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 30.0,
    )
    assert "Hello, World!" in result


@pytest.mark.asyncio
async def test_should_return_error_on_silent_failure(tmp_path: Path) -> None:
    skill_dir = tmp_path / "silent"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "quiet.py").write_text(
        "#!/usr/bin/env python3\nimport sys; sys.exit(2)\n"
    )
    skill = Skill(
        meta=SkillMeta(
            name="silent",
            description="Silent failure",
            tools=[SkillToolDef(name="quiet", description="Quietly fails")],
        ),
        path=skill_dir,
        active=True,
    )
    catalog = SkillCatalog({"silent": skill})
    sandbox = NoopBackend()
    tc = ToolCall(id="call_1", name="quiet", arguments={})
    result = await dispatch_tool_call(
        tc, catalog, sandbox, SandboxPolicy(), 30.0,
    )
    assert "failed with exit code 2" in result


@pytest.mark.asyncio
async def test_should_catch_unexpected_sandbox_exception(tmp_path: Path) -> None:
    catalog = _make_catalog_with_tool(tmp_path)

    class ExplodingSandbox:
        async def execute(self, **kwargs: object) -> None:
            raise RuntimeError("sandbox exploded")

        async def is_available(self) -> bool:
            return True

        def name(self) -> str:
            return "exploding"

    tc = ToolCall(id="call_1", name="greet", arguments={"name": "Alice"})
    result = await dispatch_tool_call(
        tc, catalog, ExplodingSandbox(), SandboxPolicy(), 30.0,
    )
    assert "Unexpected failure" in result
    assert "greet" in result
