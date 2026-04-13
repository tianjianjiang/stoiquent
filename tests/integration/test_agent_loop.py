from __future__ import annotations

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import ProviderConfig, StreamChunk


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_loop_with_ollama() -> None:
    """Full round-trip: send message -> Ollama -> streamed response.

    Requires Ollama running locally with a model available.
    Run with: uv run pytest -m integration
    """
    config = ProviderConfig(
        base_url="http://localhost:11434/v1",
        model="deepseek-r1:1.5b",
        supports_reasoning=True,
    )
    provider = OpenAICompatProvider(config)
    session = Session(provider=provider)

    chunks_received: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        chunks_received.append(chunk)

    await run_agent_loop(session, "Say hello in one word.", on_chunk)

    assert len(session.messages) == 2
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "Say hello in one word."
    assert session.messages[1].role == "assistant"
    assert session.messages[1].content is not None
    assert len(session.messages[1].content) > 0
    assert len(chunks_received) > 0

    await provider.close()
