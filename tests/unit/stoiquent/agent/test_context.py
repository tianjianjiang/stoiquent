from __future__ import annotations

from pathlib import Path

from stoiquent.agent.context import BASE_SYSTEM_PROMPT, build_messages
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import Message, ProviderConfig
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef


def _make_session(
    messages: list[Message] | None = None,
    catalog: SkillCatalog | None = None,
) -> Session:
    config = ProviderConfig(base_url="http://localhost:11434/v1", model="test")
    provider = OpenAICompatProvider(config)
    return Session(provider=provider, messages=messages or [], catalog=catalog)


def test_should_return_system_prompt_for_empty_session() -> None:
    session = _make_session()
    messages, tools = build_messages(session)
    assert len(messages) == 1
    assert messages[0].role == "system"
    assert BASE_SYSTEM_PROMPT in messages[0].content
    assert tools is None


def test_should_include_conversation_history() -> None:
    history = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    ]
    session = _make_session(history)
    messages, _tools = build_messages(session)
    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"


def test_should_place_system_prompt_first() -> None:
    session = _make_session([Message(role="user", content="test")])
    messages, _tools = build_messages(session)
    assert messages[0].role == "system"
    assert messages[0].content is not None
    assert len(messages[0].content) > 0


def test_build_messages_includes_project_instructions() -> None:
    session = _make_session()
    session.project_instructions = "Use formal tone. Prefer concise answers."

    messages, _tools = build_messages(session)

    assert messages[0].role == "system"
    assert messages[0].content is not None
    assert BASE_SYSTEM_PROMPT in messages[0].content
    assert "Use formal tone. Prefer concise answers." in messages[0].content
    # Project instructions appear after the base prompt.
    base_idx = messages[0].content.index(BASE_SYSTEM_PROMPT)
    project_idx = messages[0].content.index("Use formal tone.")
    assert base_idx < project_idx


def test_build_messages_omits_empty_project_instructions() -> None:
    session = _make_session()
    session.project_instructions = ""

    messages, _tools = build_messages(session)

    # No catalog and empty instructions → content is exactly the base prompt.
    assert messages[0].content == BASE_SYSTEM_PROMPT


def test_should_inject_catalog_into_system_prompt() -> None:
    catalog = SkillCatalog({
        "hello": Skill(
            meta=SkillMeta(name="hello", description="A greeting skill"),
            path=Path("/skills/hello"),
        ),
    })
    session = _make_session(catalog=catalog)
    messages, tools = build_messages(session)
    assert "hello" in messages[0].content
    assert "greeting skill" in messages[0].content
    assert tools is None


def test_should_inject_active_instructions() -> None:
    skill = Skill(
        meta=SkillMeta(name="hello", description="A greeting skill"),
        path=Path("/skills/hello"),
        instructions="Use the greet tool to greet people.",
        active=True,
    )
    catalog = SkillCatalog({"hello": skill})
    session = _make_session(catalog=catalog)
    messages, _tools = build_messages(session)
    assert "Use the greet tool" in messages[0].content


def test_should_return_tools_for_active_skills() -> None:
    skill = Skill(
        meta=SkillMeta(
            name="calc",
            description="Calculator",
            tools=[SkillToolDef(name="add", description="Add numbers")],
        ),
        path=Path("/skills/calc"),
        active=True,
    )
    catalog = SkillCatalog({"calc": skill})
    session = _make_session(catalog=catalog)
    _messages, tools = build_messages(session)
    assert tools is not None
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "add"


def test_should_return_no_tools_when_none_active() -> None:
    catalog = SkillCatalog({
        "hello": Skill(
            meta=SkillMeta(name="hello", description="desc"),
            path=Path("/skills/hello"),
        ),
    })
    session = _make_session(catalog=catalog)
    _messages, tools = build_messages(session)
    assert tools is None
