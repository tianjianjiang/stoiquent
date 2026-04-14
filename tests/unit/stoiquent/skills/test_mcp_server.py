from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from stoiquent.models import AppConfig, ProviderConfig
from stoiquent.skills.mcp_server import create_mcp_server


def _make_config_with_skill(tmp_path: Path) -> tuple[AppConfig, Path]:
    skill_dir = tmp_path / "skills" / "hello"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: hello\ndescription: Greeting skill\n"
        "tools:\n  - name: greet\n    description: Greet someone\n---\n"
        "Use the greet tool.\n"
    )
    (scripts_dir / "greet.py").write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        "args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}\n"
        "print(f\"Hello, {args.get('name', 'World')}!\")\n"
    )
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": [str(tmp_path / "skills")]},
    )
    return config, skill_dir


def test_should_create_server_with_tools(tmp_path: Path) -> None:
    config, _ = _make_config_with_skill(tmp_path)
    mcp = create_mcp_server(config)
    tool_names = list(mcp._tool_manager._tools.keys())
    assert "greet" in tool_names


def test_should_create_empty_server_with_no_skills(tmp_path: Path) -> None:
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": [str(tmp_path / "empty")]},
    )
    mcp = create_mcp_server(config)
    assert len(mcp._tool_manager._tools) == 0


def test_should_use_skills_dir_parameter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "extra" / "hello"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: hello\ndescription: Extra skill\n"
        "tools:\n  - name: greet\n    description: Greet\n---\n"
    )
    (scripts_dir / "greet.py").write_text("#!/usr/bin/env python3\nprint('hi')\n")

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": []},
    )
    mcp = create_mcp_server(config, skills_dir=str(tmp_path / "extra"))
    tool_names = list(mcp._tool_manager._tools.keys())
    assert "greet" in tool_names


@pytest.mark.asyncio
async def test_handler_should_execute_script(tmp_path: Path) -> None:
    config, _ = _make_config_with_skill(tmp_path)
    mcp = create_mcp_server(config)

    handler = mcp._tool_manager._tools["greet"].fn
    result = await handler(name="Alice")
    assert "Hello, Alice!" in result


@pytest.mark.asyncio
async def test_handler_should_execute_without_args(tmp_path: Path) -> None:
    config, _ = _make_config_with_skill(tmp_path)
    mcp = create_mcp_server(config)

    handler = mcp._tool_manager._tools["greet"].fn
    result = await handler()
    assert "Hello, World!" in result


@pytest.mark.asyncio
async def test_handler_should_return_error_for_missing_script(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\ndescription: Broken\n"
        "tools:\n  - name: missing\n    description: Missing\n---\n"
    )
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": [str(tmp_path / "skills")]},
    )
    mcp = create_mcp_server(config)
    handler = mcp._tool_manager._tools["missing"].fn
    result = await handler()
    assert "Error" in result
    assert "No script found" in result


@pytest.mark.asyncio
async def test_handler_should_return_error_on_nonzero_exit(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "fail"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: fail\ndescription: Failing\n"
        "tools:\n  - name: fail\n    description: Fails\n---\n"
    )
    (scripts_dir / "fail.py").write_text(
        "#!/usr/bin/env python3\nimport sys; sys.stderr.write('bad\\n'); sys.exit(1)\n"
    )
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
        skills={"paths": [str(tmp_path / "skills")]},
    )
    mcp = create_mcp_server(config)
    handler = mcp._tool_manager._tools["fail"].fn
    result = await handler()
    assert "Error (exit 1)" in result
    assert "bad" in result
