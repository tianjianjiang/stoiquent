from __future__ import annotations

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import ProviderConfig, StreamChunk

from tests.integration.conftest import skip_no_ollama


@skip_no_ollama
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_raise_on_model_not_found() -> None:
    """Ollama returns 404 for unknown models -> RuntimeError with guidance."""
    config = ProviderConfig(
        base_url="http://localhost:11434/v1",
        model="nonexistent-model-xyz:latest",
    )
    provider = OpenAICompatProvider(config)
    session = Session(provider=provider)

    async def noop(_chunk: StreamChunk) -> None:
        pass

    with pytest.raises(RuntimeError, match="not found"):
        await run_agent_loop(session, "hello", noop)

    await provider.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_raise_on_connection_refused() -> None:
    """No server running on port -> ConnectionError with guidance."""
    config = ProviderConfig(
        base_url="http://localhost:19999/v1",
        model="test",
    )
    provider = OpenAICompatProvider(config)
    session = Session(provider=provider)

    async def noop(_chunk: StreamChunk) -> None:
        pass

    with pytest.raises(ConnectionError, match="Cannot connect"):
        await run_agent_loop(session, "hello", noop)

    # No ghost assistant message -- connection failed before any content
    assert len(session.messages) == 1
    assert session.messages[0].role == "user"

    await provider.close()
