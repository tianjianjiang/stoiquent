from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.models import SkillsConfig
from stoiquent.skills.discovery import discover_skills


def _make_skill(path: Path, name: str, desc: str) -> None:
    skill_dir = path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\nInstructions for {name}."
    )


def test_should_discover_from_config_paths(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "hello", "A greeting skill")
    config = SkillsConfig(paths=[str(skills_dir)])
    result = discover_skills(config)
    assert "hello" in result
    assert result["hello"].meta.description == "A greeting skill"
    assert result["hello"].source == "config"


def test_should_skip_nonexistent_paths() -> None:
    config = SkillsConfig(paths=["/nonexistent/path"])
    result = discover_skills(config)
    assert result == {}


def test_should_skip_dirs_without_skill_md(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "no-skill").mkdir(parents=True)
    config = SkillsConfig(paths=[str(skills_dir)])
    result = discover_skills(config)
    assert result == {}


def test_should_skip_malformed_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "bad"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("No frontmatter")
    config = SkillsConfig(paths=[str(skills_dir)])
    result = discover_skills(config)
    assert result == {}


def test_should_load_instructions(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "test", "Test skill")
    config = SkillsConfig(paths=[str(skills_dir)])
    result = discover_skills(config)
    assert "Instructions for test" in result["test"].instructions


def test_project_level_overrides_config_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_skills = project_dir / ".agents" / "skills"
    _make_skill(project_skills, "dupe", "Project version")

    config_skills = tmp_path / "config-skills"
    _make_skill(config_skills, "dupe", "Config version")

    monkeypatch.chdir(project_dir)
    config = SkillsConfig(paths=[str(config_skills)])
    result = discover_skills(config)
    assert result["dupe"].source == "project"
    assert result["dupe"].meta.description == "Project version"


def test_should_discover_multiple_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "alpha", "First skill")
    _make_skill(skills_dir, "beta", "Second skill")
    config = SkillsConfig(paths=[str(skills_dir)])
    result = discover_skills(config)
    assert len(result) == 2
    assert "alpha" in result
    assert "beta" in result
