"""Integration tests for the full skill lifecycle without LLM.

Exercises: parser, discovery, catalog, executor, detect, noop, policy.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.agent.tool_dispatch import dispatch_tool_call
from stoiquent.config import load_config
from stoiquent.models import SandboxConfig, SkillsConfig, ToolCall
from stoiquent.sandbox.detect import detect_backend
from stoiquent.sandbox.policy import default_policy, merge_policy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.discovery import discover_skills
from stoiquent.skills.executor import build_command, resolve_script
from stoiquent.skills.parser import parse_skill_md

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


@pytest.mark.integration
def test_should_parse_real_skill_md() -> None:
    result = parse_skill_md(FIXTURES / "hello-world" / "SKILL.md")
    assert result is not None
    meta, body = result
    assert meta.name == "hello-world"
    assert meta.description == "A simple greeting skill for testing"
    assert len(meta.tools) == 1
    assert meta.tools[0].name == "greet"
    assert "Hello World Skill" in body


@pytest.mark.integration
def test_should_discover_skills_from_fixture_dir() -> None:
    config = SkillsConfig(paths=[str(FIXTURES)])
    skills = discover_skills(config)
    assert "hello-world" in skills
    assert skills["hello-world"].meta.name == "hello-world"
    assert skills["hello-world"].source == "config"


@pytest.mark.integration
def test_should_activate_and_get_tools() -> None:
    config = SkillsConfig(paths=[str(FIXTURES)])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)

    assert catalog.activate("hello-world") is True
    active = catalog.get_active_skills()
    assert len(active) == 1

    tools = catalog.get_active_tools()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "greet"

    prompt = catalog.get_catalog_prompt()
    assert "hello-world" in prompt
    assert "[active]" in prompt

    instructions = catalog.get_active_instructions()
    assert "Hello World Skill" in instructions


@pytest.mark.integration
def test_should_deactivate_skill() -> None:
    config = SkillsConfig(paths=[str(FIXTURES)])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)
    catalog.activate("hello-world")
    catalog.deactivate("hello-world")
    assert catalog.get_active_skills() == []
    assert catalog.get_active_tools() == []


@pytest.mark.integration
def test_should_resolve_and_build_command() -> None:
    skill_path = FIXTURES / "hello-world"
    script = resolve_script(skill_path, "greet")
    assert script is not None
    assert script.name == "greet.py"

    command = build_command(script)
    assert command[0] == "python3"
    assert str(script) in command


@pytest.mark.integration
def test_should_detect_backend_on_auto() -> None:
    sandbox_config = SandboxConfig(backend="auto")
    backend = detect_backend(sandbox_config)
    assert backend.name() in ("noop", "apple-containers", "oci:docker", "oci:podman", "oci:finch")
    assert await_is_available(backend)


def await_is_available(backend: object) -> bool:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(backend.is_available())


@pytest.mark.integration
def test_should_use_default_and_merge_policy() -> None:
    policy = default_policy()
    assert policy.cpu_seconds == 120.0
    assert policy.network == "none"

    merged = merge_policy(policy, {"memory_mb": 1024})
    assert merged.memory_mb == 1024
    assert merged.cpu_seconds == 120.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_tool_via_sandbox() -> None:
    """Full pipeline: discover -> activate -> dispatch -> sandbox execute."""
    config = SkillsConfig(paths=[str(FIXTURES)])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)
    catalog.activate("hello-world")

    sandbox_config = SandboxConfig(backend="none")
    sandbox = detect_backend(sandbox_config)
    policy = default_policy()

    tc = ToolCall(id="call_1", name="greet", arguments={"name": "Integration"})
    result = await dispatch_tool_call(tc, catalog, sandbox, policy, 30.0)
    assert "Hello, Integration!" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_tool_without_arguments() -> None:
    config = SkillsConfig(paths=[str(FIXTURES)])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)
    catalog.activate("hello-world")

    sandbox = detect_backend(SandboxConfig(backend="none"))
    tc = ToolCall(id="call_1", name="greet", arguments={})
    result = await dispatch_tool_call(tc, catalog, sandbox, default_policy(), 30.0)
    assert "Hello, World!" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_error_for_unknown_tool() -> None:
    config = SkillsConfig(paths=[str(FIXTURES)])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)
    catalog.activate("hello-world")

    sandbox = detect_backend(SandboxConfig(backend="none"))
    tc = ToolCall(id="call_1", name="nonexistent", arguments={})
    result = await dispatch_tool_call(tc, catalog, sandbox, default_policy(), 30.0)
    assert "Error" in result
    assert "Unknown tool" in result


@pytest.mark.integration
def test_should_load_config_with_all_sections() -> None:
    config = load_config(Path("stoiquent.toml"))
    assert config.skills.paths == ["~/.agents/skills", "~/.stoiquent/skills"]
    assert config.sandbox.backend == "auto"
    assert config.persistence.data_dir == "~/.stoiquent"
    assert config.agent.iteration_limit == 25


@pytest.mark.integration
def test_should_load_config_with_env_interpolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("""\
[llm]
default = "test"

[llm.providers.test]
type = "openai"
base_url = "http://localhost:11434/v1"
model = "test"
api_key = "${TEST_KEY}"

[skills]
paths = ["${SKILLS_DIR}/custom"]
""")
    monkeypatch.setenv("TEST_KEY", "secret123")
    monkeypatch.setenv("SKILLS_DIR", "/opt")
    config = load_config(config_file)
    assert config.providers["test"].api_key == "secret123"
    assert config.skills.paths == ["/opt/custom"]


@pytest.mark.integration
def test_should_parse_skill_with_multiple_tools(tmp_path: Path) -> None:
    skill_dir = tmp_path / "multi"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("""\
---
name: multi
description: Multi-tool skill
tools:
  - name: tool_a
    description: First tool
  - name: tool_b
    description: Second tool
---
Instructions here.
""")
    (scripts_dir / "tool_a.py").write_text("#!/usr/bin/env python3\nprint('A')\n")
    (scripts_dir / "tool_b.py").write_text("#!/usr/bin/env python3\nprint('B')\n")

    result = parse_skill_md(skill_dir / "SKILL.md")
    assert result is not None
    meta, body = result
    assert len(meta.tools) == 2

    config = SkillsConfig(paths=[str(tmp_path)])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)
    catalog.activate("multi")

    sandbox = detect_backend(SandboxConfig(backend="none"))

    tc_a = ToolCall(id="call_1", name="tool_a", arguments={})
    result_a = await_dispatch(tc_a, catalog, sandbox)
    assert "A" in result_a

    tc_b = ToolCall(id="call_2", name="tool_b", arguments={})
    result_b = await_dispatch(tc_b, catalog, sandbox)
    assert "B" in result_b


def await_dispatch(tc: ToolCall, catalog: SkillCatalog, sandbox: object) -> str:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        dispatch_tool_call(tc, catalog, sandbox, default_policy(), 30.0)
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_bash_script_via_sandbox(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "bash-skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bash-skill\ndescription: Bash tool\n"
        "tools:\n  - name: hello_bash\n    description: Bash hello\n---\n"
    )
    (scripts_dir / "hello_bash.sh").write_text("#!/bin/bash\necho 'Bash hello!'\n")

    config = SkillsConfig(paths=[str(tmp_path / "skills")])
    skills = discover_skills(config)
    catalog = SkillCatalog(skills)
    catalog.activate("bash-skill")

    sandbox = detect_backend(SandboxConfig(backend="none"))
    tc = ToolCall(id="call_1", name="hello_bash", arguments={})
    result = await dispatch_tool_call(tc, catalog, sandbox, default_policy(), 30.0)
    assert "Bash hello!" in result


@pytest.mark.integration
def test_reasoning_extraction_with_think_tags() -> None:
    from stoiquent.llm.reasoning import extract_reasoning

    content = "<think>Step 1: analyze\nStep 2: conclude</think>The answer is 42."
    clean, reasoning = extract_reasoning(content)
    assert clean == "The answer is 42."
    assert "Step 1" in reasoning
    assert "Step 2" in reasoning


@pytest.mark.integration
def test_reasoning_passthrough_without_tags() -> None:
    from stoiquent.llm.reasoning import extract_reasoning

    content = "Just a plain answer."
    clean, reasoning = extract_reasoning(content)
    assert clean == "Just a plain answer."
    assert reasoning is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_noop_sandbox_timeout() -> None:
    import sys
    from stoiquent.sandbox.noop import NoopBackend
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        default_policy(),
        timeout=0.2,
    )
    assert result.timed_out is True
    assert result.exit_code == -1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_noop_sandbox_command_not_found() -> None:
    from stoiquent.sandbox.noop import NoopBackend
    backend = NoopBackend()
    result = await backend.execute(
        ["/nonexistent/binary/12345"],
        default_policy(),
    )
    assert result.exit_code == 127
    assert "not found" in result.stderr.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_noop_sandbox_with_stdin() -> None:
    import sys
    from stoiquent.sandbox.noop import NoopBackend
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
        default_policy(),
        stdin="hello from stdin",
    )
    assert result.exit_code == 0
    assert "hello from stdin" in result.stdout


@pytest.mark.integration
def test_executor_shebang_and_pep723(tmp_path: Path) -> None:
    # Python with shebang
    py_script = tmp_path / "test.py"
    py_script.write_text("#!/usr/bin/env python3\nprint('hi')\n")
    cmd = build_command(py_script)
    assert cmd[0] == "python3"

    # Bash with shebang
    sh_script = tmp_path / "test.sh"
    sh_script.write_text("#!/bin/bash\necho hi\n")
    cmd = build_command(sh_script)
    assert "/bin/bash" in cmd[0]

    # PEP 723 script
    pep723 = tmp_path / "pep.py"
    pep723.write_text("#!/usr/bin/env python3\n# /// script\n# dependencies = ['requests']\n# ///\n")
    cmd = build_command(pep723)
    assert cmd[0] == "uv"
    assert cmd[1] == "run"

    # Unknown extension without shebang
    txt = tmp_path / "test.txt"
    txt.write_text("echo hi\n")
    cmd = build_command(txt)
    assert cmd[0] == "sh"

    # Script resolution by stem
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "mytool.py").write_text("print('hi')\n")
    resolved = resolve_script(tmp_path, "mytool")
    assert resolved is not None
    assert resolved.name == "mytool.py"


@pytest.mark.integration
def test_executor_resolve_by_exact_name(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "exact.py").write_text("print('exact')\n")
    resolved = resolve_script(tmp_path, "exact.py")
    assert resolved is not None
    assert resolved.name == "exact.py"


@pytest.mark.integration
def test_executor_path_traversal_rejected(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "legit.py").write_text("print('hi')\n")
    assert resolve_script(tmp_path, "../../etc/passwd") is None


@pytest.mark.integration
def test_executor_executable_script(tmp_path: Path) -> None:
    script = tmp_path / "run_me"
    script.write_text("echo hi\n")
    script.chmod(0o755)
    cmd = build_command(script)
    assert cmd == [str(script)]


@pytest.mark.integration
def test_executor_pep723_without_shebang(tmp_path: Path) -> None:
    script = tmp_path / "deps.py"
    script.write_text("# /// script\n# dependencies = ['requests']\n# ///\nimport requests\n")
    cmd = build_command(script)
    assert cmd[0] == "uv"
    assert cmd[1] == "run"


@pytest.mark.integration
def test_executor_missing_scripts_dir(tmp_path: Path) -> None:
    assert resolve_script(tmp_path, "anything") is None


@pytest.mark.integration
def test_executor_full_path_shebang(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text("#!/usr/bin/python3\nprint('hi')\n")
    cmd = build_command(script)
    assert cmd[0] == "python3"


@pytest.mark.integration
def test_parser_edge_cases(tmp_path: Path) -> None:
    # No frontmatter
    no_fm = tmp_path / "no_fm.md"
    no_fm.write_text("Just content, no frontmatter.")
    assert parse_skill_md(no_fm) is None

    # Invalid YAML
    bad_yaml = tmp_path / "bad.md"
    bad_yaml.write_text("---\n: [invalid\n---\nBody")
    assert parse_skill_md(bad_yaml) is None

    # Missing required field
    no_desc = tmp_path / "no_desc.md"
    no_desc.write_text("---\nname: test\n---\nBody")
    assert parse_skill_md(no_desc) is None

    # Valid with empty body
    empty_body = tmp_path / "empty.md"
    empty_body.write_text("---\nname: test\ndescription: A test\n---\n")
    result = parse_skill_md(empty_body)
    assert result is not None
    assert result[0].name == "test"

    # Non-dict frontmatter
    non_dict = tmp_path / "list.md"
    non_dict.write_text("---\n- just a list\n---\nBody")
    assert parse_skill_md(non_dict) is None
