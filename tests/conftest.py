from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk

pytest_plugins = ["nicegui.testing.plugin"]


@dataclass
class FakeProvider:
    """Deterministic LLM provider for testing. Not a mock -- a real implementation
    of the LLMProvider protocol that yields pre-configured chunks."""

    chunks: list[StreamChunk] = field(default_factory=list)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self.chunks:
            yield chunk


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider(
        chunks=[
            StreamChunk(content_delta="Hello from fake!"),
            StreamChunk(finish_reason="stop"),
        ]
    )


@pytest.fixture
def fake_session(fake_provider: FakeProvider) -> Session:
    return Session(provider=fake_provider)
