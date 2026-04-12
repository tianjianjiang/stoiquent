from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from stoiquent.models import Message, StreamChunk


@runtime_checkable
class LLMProvider(Protocol):
    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...
