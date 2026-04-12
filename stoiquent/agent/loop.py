from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from stoiquent.agent.context import build_messages
from stoiquent.agent.session import Session
from stoiquent.llm.reasoning import extract_reasoning
from stoiquent.models import Message, StreamChunk

OnChunkCallback = Callable[[StreamChunk], Coroutine[Any, Any, None]]


async def run_agent_loop(
    session: Session,
    user_message: str,
    on_chunk: OnChunkCallback,
) -> None:
    session.messages.append(Message(role="user", content=user_message))
    messages = build_messages(session)

    raw_content = ""
    api_reasoning = ""

    try:
        async for chunk in session.provider.stream(messages):
            if chunk.content_delta:
                raw_content += chunk.content_delta
            if chunk.reasoning_delta:
                api_reasoning += chunk.reasoning_delta
            await on_chunk(chunk)
    finally:
        if api_reasoning:
            final_reasoning = api_reasoning
            final_content = raw_content or None
        else:
            final_content, final_reasoning = extract_reasoning(raw_content)
            final_content = final_content or None
            final_reasoning = final_reasoning or None

        session.messages.append(
            Message(
                role="assistant",
                content=final_content,
                reasoning=final_reasoning,
            )
        )
