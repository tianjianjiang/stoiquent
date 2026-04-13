from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk
from stoiquent.ui.chat import ChatPanel


@dataclass
class FakeProvider:
    chunks: list[StreamChunk] = field(default_factory=list)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_should_render_input_and_button(user: User) -> None:
    provider = FakeProvider()
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-render")
    async def page() -> None:
        panel.render()

    await user.open("/test-render")
    await user.should_see("Type a message...")
    await user.should_see("Send")


@pytest.mark.asyncio
async def test_should_guard_concurrent_sends(user: User) -> None:
    provider = FakeProvider()
    session = Session(provider=provider)
    panel = ChatPanel(session)
    panel._sending = True

    @ui.page("/test-guard")
    async def page() -> None:
        panel.render()

    await user.open("/test-guard")
    # Calling _send when _sending=True should be a no-op
    await panel._send()
    assert len(session.messages) == 0


@pytest.mark.asyncio
async def test_should_send_message_via_ui(user: User) -> None:
    chunks = [
        StreamChunk(content_delta="Hello!"),
        StreamChunk(finish_reason="stop"),
    ]
    provider = FakeProvider(chunks=chunks)
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-send")
    async def page() -> None:
        panel.render()

    await user.open("/test-send")
    user.find("Type a message...").type("Hi")
    user.find("Send").click()
    await user.should_see("Hello!")


@pytest.mark.asyncio
async def test_should_reset_sending_flag_after_completion(user: User) -> None:
    chunks = [StreamChunk(finish_reason="stop")]
    provider = FakeProvider(chunks=chunks)
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-reset")
    async def page() -> None:
        panel.render()

    await user.open("/test-reset")
    user.find("Type a message...").type("Hi")
    user.find("Send").click()

    # After completion, _sending should be reset
    assert panel._sending is False
