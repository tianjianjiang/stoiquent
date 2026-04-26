from __future__ import annotations

from pathlib import Path

from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef


def _make_skill(
    name: str, desc: str = "A test skill", active: bool = False
) -> Skill:
    return Skill(
        meta=SkillMeta(name=name, description=desc),
        path=Path(f"/skills/{name}"),
        instructions=f"Instructions for {name}",
        active=active,
    )


def _make_skill_with_tool(name: str) -> Skill:
    return Skill(
        meta=SkillMeta(
            name=name,
            description="Skill with tool",
            tools=[
                SkillToolDef(
                    name=f"{name}_tool",
                    description=f"Tool from {name}",
                    parameters={
                        "type": "object",
                        "properties": {"arg": {"type": "string"}},
                    },
                )
            ],
        ),
        path=Path(f"/skills/{name}"),
        instructions=f"Instructions for {name}",
    )


def test_should_create_empty_catalog() -> None:
    catalog = SkillCatalog()
    assert catalog.skills == {}
    assert catalog.get_catalog_prompt() == ""
    assert catalog.get_active_tools() == []


def test_should_create_catalog_with_skills() -> None:
    skills = {"hello": _make_skill("hello")}
    catalog = SkillCatalog(skills)
    assert "hello" in catalog.skills


def test_should_activate_skill() -> None:
    catalog = SkillCatalog({"hello": _make_skill("hello")})
    assert catalog.activate("hello") is True
    assert catalog.skills["hello"].active is True


def test_should_return_true_for_already_active() -> None:
    catalog = SkillCatalog({"hello": _make_skill("hello", active=True)})
    assert catalog.activate("hello") is True


def test_should_return_false_for_unknown_skill_activate() -> None:
    catalog = SkillCatalog()
    assert catalog.activate("unknown") is False


def test_should_deactivate_skill() -> None:
    catalog = SkillCatalog({"hello": _make_skill("hello", active=True)})
    assert catalog.deactivate("hello") is True
    assert catalog.skills["hello"].active is False


def test_should_return_true_for_already_inactive() -> None:
    catalog = SkillCatalog({"hello": _make_skill("hello")})
    assert catalog.deactivate("hello") is True


def test_should_return_false_for_unknown_skill_deactivate() -> None:
    catalog = SkillCatalog()
    assert catalog.deactivate("unknown") is False


def test_should_get_active_skills() -> None:
    catalog = SkillCatalog({
        "a": _make_skill("a", active=True),
        "b": _make_skill("b", active=False),
        "c": _make_skill("c", active=True),
    })
    active = catalog.get_active_skills()
    names = {s.meta.name for s in active}
    assert names == {"a", "c"}


def test_should_generate_catalog_prompt() -> None:
    catalog = SkillCatalog({
        "hello": _make_skill("hello", active=True),
        "world": _make_skill("world", desc="World skill"),
    })
    prompt = catalog.get_catalog_prompt()
    assert "hello" in prompt
    assert "world" in prompt
    assert "[active]" in prompt
    assert "[available]" in prompt


def test_should_get_active_tools() -> None:
    catalog = SkillCatalog({
        "a": _make_skill_with_tool("a"),
        "b": _make_skill_with_tool("b"),
    })
    catalog.activate("a")
    tools = catalog.get_active_tools()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "a_tool"


def test_should_return_empty_tools_when_none_active() -> None:
    catalog = SkillCatalog({"a": _make_skill_with_tool("a")})
    assert catalog.get_active_tools() == []


def test_should_get_active_instructions() -> None:
    catalog = SkillCatalog({
        "hello": _make_skill("hello", active=True),
        "world": _make_skill("world"),
    })
    instructions = catalog.get_active_instructions()
    assert "Instructions for hello" in instructions
    assert "Instructions for world" not in instructions


def test_should_not_mutate_original_skills_dict() -> None:
    original = {"hello": _make_skill("hello")}
    catalog = SkillCatalog(original)
    catalog.activate("hello")
    assert original["hello"].active is False


def test_replace_swaps_catalog_contents() -> None:
    catalog = SkillCatalog({"old": _make_skill("old", active=True)})
    catalog.replace({"new": _make_skill("new")})
    assert "old" not in catalog.skills
    assert "new" in catalog.skills


def test_replace_copies_dict_so_caller_mutations_do_not_leak() -> None:
    catalog = SkillCatalog()
    new_contents = {"a": _make_skill("a")}
    catalog.replace(new_contents)
    new_contents["b"] = _make_skill("b")
    assert "b" not in catalog.skills
