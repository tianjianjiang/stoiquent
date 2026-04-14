from __future__ import annotations

from pathlib import Path

from stoiquent.skills.parser import parse_skill_md


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "skills"


def test_should_parse_valid_skill_md() -> None:
    result = parse_skill_md(FIXTURES / "hello-world" / "SKILL.md")
    assert result is not None
    meta, body = result
    assert meta.name == "hello-world"
    assert meta.description == "A simple greeting skill for testing"
    assert meta.version == "1.0"
    assert "example" in meta.tags
    assert len(meta.tools) == 1
    assert meta.tools[0].name == "greet"
    assert "Hello World Skill" in body


def test_should_return_none_for_missing_file(tmp_path: Path) -> None:
    result = parse_skill_md(tmp_path / "nonexistent.md")
    assert result is None


def test_should_return_none_for_no_frontmatter(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("# Just a heading\nNo frontmatter here.")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_return_none_for_invalid_yaml(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\n: invalid: yaml: [[\n---\nBody")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_return_none_for_non_dict_frontmatter(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\n- just a list\n---\nBody")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_return_none_for_missing_description(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: test\n---\nBody")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_return_none_for_missing_name(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\ndescription: test\n---\nBody")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_return_none_for_unclosed_frontmatter(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: test\ndescription: test\nBody without closing")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_handle_empty_body(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: test\ndescription: A test\n---\n")
    result = parse_skill_md(skill_md)
    assert result is not None
    meta, body = result
    assert meta.name == "test"
    assert body == ""


def test_should_reject_partial_closing_fence(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: test\ndescription: A test\n---extra\nBody")
    result = parse_skill_md(skill_md)
    assert result is None


def test_should_allow_extra_fields_in_frontmatter(tmp_path: Path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: test\ndescription: A test\ncustom: value\n---\nBody"
    )
    result = parse_skill_md(skill_md)
    assert result is not None
    meta, _ = result
    assert meta.model_extra == {"custom": "value"}
