from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from stoiquent.models import AppConfig, ProviderConfig
from stoiquent.skills.mcp_server import create_mcp_server
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef


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
        "#!/usr/bin/env python3\nprint('Hello!')\n"
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
