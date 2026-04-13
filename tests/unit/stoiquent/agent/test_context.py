from __future__ import annotations

from stoiquent.agent.context import BASE_SYSTEM_PROMPT, build_messages
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import Message, ProviderConfig


def _make_session(messages: list[Message] | None = None) -> Session:
    config = ProviderConfig(base_url="http://localhost:11434/v1", model="test")
    provider = OpenAICompatProvider(config)
    return Session(provider=provider, messages=messages or [])


def test_should_return_system_prompt_for_empty_session() -> None:
    session = _make_session()
    messages = build_messages(session)
    assert len(messages) == 1
    assert messages[0].role == "system"
    assert messages[0].content == BASE_SYSTEM_PROMPT


def test_should_include_conversation_history() -> None:
    history = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    ]
    session = _make_session(history)
    messages = build_messages(session)
    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"


def test_should_place_system_prompt_first() -> None:
    session = _make_session([Message(role="user", content="test")])
    messages = build_messages(session)
    assert messages[0].role == "system"
    assert messages[0].content is not None
    assert len(messages[0].content) > 0
