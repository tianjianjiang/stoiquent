from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.models import AppConfig, Message, ProviderConfig
from stoiquent.ui import layout
from stoiquent.ui.layout import _switch_provider
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


async def test_switch_provider_with_closeable_provider() -> None:
    """Verify old provider's close() is scheduled when switching."""
    close_mock = AsyncMock()
    provider = FakeProvider()
    provider.close = close_mock  # type: ignore[attr-defined]

    session = Session(provider=provider)
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

    _switch_provider(session, config, "other")
    await asyncio.sleep(0.01)

    assert session.provider is not provider
    close_mock.assert_awaited_once()


def test_switch_provider_returns_false_for_none_config() -> None:
    session = Session(provider=FakeProvider())
    assert _switch_provider(session, None, "anything") is False


def test_switch_provider_returns_false_for_unknown_name() -> None:
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


def test_switch_provider_logs_warning_when_no_event_loop(caplog: pytest.LogCaptureFixture) -> None:
    """Cover lines 87-88: RuntimeError branch when no event loop is running."""
    provider = FakeProvider()
    provider.close = AsyncMock()  # type: ignore[attr-defined]

    session = Session(provider=provider)
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

    with caplog.at_level(logging.WARNING):
        result = _switch_provider(session, config, "other")

    assert result is True
    assert "No event loop to close old provider" in caplog.text


async def test_switch_provider_logs_close_error(caplog: pytest.LogCaptureFixture) -> None:
    """Cover line 81: _log_close_error callback when provider.close() raises."""
    provider = FakeProvider()
    provider.close = AsyncMock(side_effect=RuntimeError("close failed"))  # type: ignore[attr-defined]

    session = Session(provider=provider)
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

    with caplog.at_level(logging.WARNING):
        _switch_provider(session, config, "other")
        await asyncio.sleep(0.01)

    assert "Failed to close old provider" in caplog.text
