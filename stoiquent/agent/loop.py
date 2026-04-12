from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from stoiquent.agent.context import build_messages
from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk

OnChunkCallback = Callable[[StreamChunk], Coroutine[Any, Any, None]]


async def run_agent_loop(
    session: Session,
    user_message: str,
    on_chunk: OnChunkCallback,
) -> None:
    session.messages.append(Message(role="user", content=user_message))
    messages = build_messages(session)

    assistant_content = ""
    assistant_reasoning = ""

    async for chunk in session.provider.stream(messages):
        if chunk.content_delta:
            assistant_content += chunk.content_delta
        if chunk.reasoning_delta:
            assistant_reasoning += chunk.reasoning_delta
        await on_chunk(chunk)

    session.messages.append(
        Message(
            role="assistant",
            content=assistant_content or None,
            reasoning=assistant_reasoning or None,
        )
    )
