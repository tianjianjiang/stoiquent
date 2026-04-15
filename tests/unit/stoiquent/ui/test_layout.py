from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.models import AppConfig, Message, ProviderConfig
from stoiquent.ui import layout
from tests.conftest import FakeProvider


@pytest.mark.asyncio
async def test_should_render_layout_with_header_and_sidebar(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/test-layout")
    async def page() -> None:
        await layout.render(session)

    await user.open("/test-layout")
    await user.should_see("Stoiquent")
    await user.should_see("Sessions")
    await user.should_see("Skills")
    await user.should_see("New Chat")


@pytest.mark.asyncio
async def test_should_render_local_llm_label(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/test-label")
    async def page() -> None:
        await layout.render(session)

    await user.open("/test-label")
    await user.should_see("Local LLM Agent")


@pytest.mark.asyncio
async def test_should_render_provider_dropdown(user: User) -> None:
    session = Session(provider=FakeProvider())
    config = AppConfig(
        default_provider="local-qwen",
        providers={
            "local-qwen": ProviderConfig(
                base_url="http://localhost:11434/v1", model="qwen3:32b"
            ),
            "cloud-gpt": ProviderConfig(
                base_url="https://api.openai.com/v1", model="gpt-4"
            ),
        },
    )

    @ui.page("/test-dropdown")
    async def page() -> None:
        await layout.render(session, config=config)

    await user.open("/test-dropdown")
    await user.should_see("Stoiquent")
    await user.should_see("local-qwen")


@pytest.mark.asyncio
async def test_session_switch_updates_messages(user: User) -> None:
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Old")]

    from stoiquent.ui.chat import ChatPanel

    chat = ChatPanel(session)

    def on_switch(new_id: str, new_msgs: list[Message]) -> None:
        session.id = new_id
        session.messages = new_msgs
        chat.reload_messages()

    on_switch("new123", [Message(role="user", content="Reloaded")])

    assert session.id == "new123"
    assert len(session.messages) == 1
    assert session.messages[0].content == "Reloaded"


def test_switch_provider_changes_session_provider() -> None:
    from stoiquent.ui.layout import _switch_provider

    session = Session(provider=FakeProvider())
    config = AppConfig(
        default_provider="local-qwen",
        providers={
            "local-qwen": ProviderConfig(
                base_url="http://localhost:11434/v1", model="qwen3:32b"
            ),
            "other": ProviderConfig(
                base_url="http://localhost:11434/v1", model="other-model"
            ),
        },
    )

    original = session.provider
    result = _switch_provider(session, config, "other")
    assert result is True
    assert session.provider is not original


def test_switch_provider_returns_false_for_unknown_name() -> None:
    from stoiquent.ui.layout import _switch_provider

    session = Session(provider=FakeProvider())
    config = AppConfig(
        default_provider="local-qwen",
        providers={
            "local-qwen": ProviderConfig(
                base_url="http://localhost:11434/v1", model="qwen3:32b"
            ),
        },
    )

    original = session.provider
    result = _switch_provider(session, config, "nonexistent")
    assert result is False
    assert session.provider is original
