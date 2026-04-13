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


@pytest.mark.asyncio
async def test_should_ignore_whitespace_only_input(user: User) -> None:
    provider = FakeProvider()
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-whitespace")
    async def page() -> None:
        panel.render()

    await user.open("/test-whitespace")
    # Set whitespace directly to bypass NiceGUI input normalization
    panel._input.value = "   "
    await panel._send()
    assert len(session.messages) == 0


@pytest.mark.asyncio
async def test_should_ignore_empty_input_value(user: User) -> None:
    provider = FakeProvider()
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-empty")
    async def page() -> None:
        panel.render()

    await user.open("/test-empty")
    panel._input.value = ""
    await panel._send()
    assert len(session.messages) == 0


@pytest.mark.asyncio
async def test_should_raise_when_render_not_called(user: User) -> None:
    provider = FakeProvider()
    session = Session(provider=provider)
    panel = ChatPanel(session)
    panel._input = type("FakeInput", (), {"value": "test"})()

    with pytest.raises(RuntimeError, match="render"):
        await panel._send()


@pytest.mark.asyncio
async def test_should_display_reasoning_expansion(user: User) -> None:
    chunks = [
        StreamChunk(reasoning_delta="Let me "),
        StreamChunk(reasoning_delta="think..."),
        StreamChunk(content_delta="The answer is 42."),
        StreamChunk(finish_reason="stop"),
    ]
    provider = FakeProvider(chunks=chunks)
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-reasoning")
    async def page() -> None:
        panel.render()

    await user.open("/test-reasoning")
    user.find("Type a message...").type("What is the answer?")
    user.find("Send").click()
    await user.should_see("The answer is 42.")


@pytest.mark.asyncio
async def test_should_display_connection_error_message(user: User) -> None:
    async def failing_stream(messages, tools=None):
        raise ConnectionError("Cannot connect to LLM")
        yield  # noqa: RUF027

    provider = FakeProvider()
    provider.stream = failing_stream  # type: ignore[assignment]
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-conn-err")
    async def page() -> None:
        panel.render()

    await user.open("/test-conn-err")
    user.find("Type a message...").type("Hello")
    user.find("Send").click()
    await user.should_see("Connection error")


@pytest.mark.asyncio
async def test_should_display_generic_error_message(
    user: User, caplog: pytest.LogCaptureFixture
) -> None:
    async def exploding_stream(messages, tools=None):
        raise ValueError("unexpected boom")
        yield  # noqa: RUF027

    provider = FakeProvider()
    provider.stream = exploding_stream  # type: ignore[assignment]
    session = Session(provider=provider)
    panel = ChatPanel(session)

    @ui.page("/test-generic-err")
    async def page() -> None:
        panel.render()

    await user.open("/test-generic-err")
    user.find("Type a message...").type("Hello")
    user.find("Send").click()
    await user.should_see("An unexpected error occurred")

    # Clear ERROR logs so NiceGUI's teardown check does not fail
    caplog.clear()
