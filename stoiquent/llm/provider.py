from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from stoiquent.models import Message, StreamChunk


class LLMProvider(Protocol):
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...
