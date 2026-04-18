from __future__ import annotations

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import StreamChunk

from tests.integration.conftest import skip_no_model, skip_no_ollama


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_complete_full_round_trip(
    provider: OpenAICompatProvider,
) -> None:
    """User message -> Ollama -> streamed response -> session updated."""
    session = Session(provider=provider)
    chunks: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        chunks.append(chunk)

    await run_agent_loop(session, "Say hello in one word.", on_chunk)

    assert len(session.messages) == 2
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "Say hello in one word."
    assert session.messages[1].role == "assistant"
    assert session.messages[1].content is not None
    assert len(session.messages[1].content) > 0
    assert len(chunks) > 0


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_extract_reasoning_from_deepseek_r1(
    provider: OpenAICompatProvider,
) -> None:
    """DeepSeek-R1 returns reasoning via 'reasoning' field in SSE delta."""
    session = Session(provider=provider)

    async def on_chunk(_chunk: StreamChunk) -> None:
        pass

    await run_agent_loop(session, "What is 2+3? Think step by step.", on_chunk)

    assistant = session.messages[1]
    assert assistant.content is not None
    assert len(assistant.content) > 0
    assert assistant.reasoning is not None
    assert len(assistant.reasoning) > 0


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_stream_content_and_reasoning_separately(
    provider: OpenAICompatProvider,
) -> None:
    """Verify content_delta and reasoning_delta arrive in separate chunks."""
    session = Session(provider=provider)
    content_chunks: list[str] = []
    reasoning_chunks: list[str] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        if chunk.content_delta:
            content_chunks.append(chunk.content_delta)
        if chunk.reasoning_delta:
            reasoning_chunks.append(chunk.reasoning_delta)

    await run_agent_loop(session, "What is 1+1? Explain your reasoning step by step.", on_chunk)

    assert len(content_chunks) > 0
    if not reasoning_chunks:
        pytest.skip("Model did not produce reasoning for this prompt")
    assert "".join(content_chunks) == session.messages[1].content
    assert "".join(reasoning_chunks) == session.messages[1].reasoning


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_accumulate_multi_turn_history(
    provider: OpenAICompatProvider,
) -> None:
    """Two consecutive messages build up session history correctly."""
    session = Session(provider=provider)

    async def noop(_chunk: StreamChunk) -> None:
        pass

    await run_agent_loop(session, "Say hello.", noop)
    assert len(session.messages) == 2

    await run_agent_loop(session, "Say goodbye.", noop)
    assert len(session.messages) == 4
    assert session.messages[0].role == "user"
    assert session.messages[1].role == "assistant"
    assert session.messages[2].role == "user"
    assert session.messages[2].content == "Say goodbye."
    assert session.messages[3].role == "assistant"
    assert session.messages[3].content is not None

