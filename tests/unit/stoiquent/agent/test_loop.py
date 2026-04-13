from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from stoiquent.agent.loop import OnChunkCallback, run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk


async def _async_noop(_chunk: StreamChunk) -> None:
    pass


def _async_append(target: list[StreamChunk]) -> OnChunkCallback:
    async def _cb(chunk: StreamChunk) -> None:
        target.append(chunk)
    return _cb


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
async def test_should_accumulate_content_into_assistant_message() -> None:
    provider = FakeProvider(
        chunks=[
            StreamChunk(content_delta="Hello "),
            StreamChunk(content_delta="world!"),
            StreamChunk(finish_reason="stop"),
        ]
    )
    session = Session(provider=provider)
    received: list[StreamChunk] = []
    await run_agent_loop(session, "Hi", _async_append(received))

    assert len(session.messages) == 2
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "Hi"
    assert session.messages[1].role == "assistant"
    assert session.messages[1].content == "Hello world!"
    assert len(received) == 3


@pytest.mark.asyncio
async def test_should_extract_reasoning_from_think_tags() -> None:
    provider = FakeProvider(
        chunks=[
            StreamChunk(content_delta="<think>Let me think</think>The answer is 42."),
            StreamChunk(finish_reason="stop"),
        ]
    )
    session = Session(provider=provider)
    await run_agent_loop(session, "What?", _async_noop)

    assistant = session.messages[1]
    assert assistant.content == "The answer is 42."
    assert assistant.reasoning == "Let me think"


@pytest.mark.asyncio
async def test_should_use_api_reasoning_when_present() -> None:
    provider = FakeProvider(
        chunks=[
            StreamChunk(content_delta="answer", reasoning_delta="thinking..."),
            StreamChunk(finish_reason="stop"),
        ]
    )
    session = Session(provider=provider)
    await run_agent_loop(session, "Q", _async_noop)

    assistant = session.messages[1]
    assert assistant.content == "answer"
    assert assistant.reasoning == "thinking..."


@pytest.mark.asyncio
async def test_should_not_append_message_for_empty_response() -> None:
    provider = FakeProvider(chunks=[StreamChunk(finish_reason="stop")])
    session = Session(provider=provider)
    await run_agent_loop(session, "Hi", _async_noop)

    assert len(session.messages) == 1
    assert session.messages[0].role == "user"


@pytest.mark.asyncio
async def test_should_append_message_even_on_stream_error() -> None:
    async def failing_stream(
        messages: list[Message], tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content_delta="partial ")
        raise ConnectionError("lost connection")

    provider = FakeProvider()
    provider.stream = failing_stream  # type: ignore[assignment]
    session = Session(provider=provider)

    with pytest.raises(ConnectionError):
        await run_agent_loop(session, "Hi", _async_noop)

    assert len(session.messages) == 2
    assert session.messages[1].role == "assistant"
    assert session.messages[1].content == "partial "


@pytest.mark.asyncio
async def test_should_not_append_ghost_message_on_immediate_error() -> None:
    async def failing_stream(
        messages: list[Message], tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        raise ConnectionError("connection refused")
        yield  # make it a generator  # noqa: RUF027

    provider = FakeProvider()
    provider.stream = failing_stream  # type: ignore[assignment]
    session = Session(provider=provider)

    with pytest.raises(ConnectionError):
        await run_agent_loop(session, "Hi", _async_noop)

    assert len(session.messages) == 1
    assert session.messages[0].role == "user"


@pytest.mark.asyncio
async def test_should_invoke_callback_for_every_chunk() -> None:
    provider = FakeProvider(
        chunks=[
            StreamChunk(content_delta="a"),
            StreamChunk(content_delta="b"),
            StreamChunk(content_delta="c"),
        ]
    )
    session = Session(provider=provider)
    received: list[StreamChunk] = []
    await run_agent_loop(session, "Hi", _async_append(received))
    assert len(received) == 3
