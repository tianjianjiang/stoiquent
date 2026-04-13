from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from stoiquent.agent.context import build_messages
from stoiquent.agent.session import Session
from stoiquent.agent.tool_dispatch import dispatch_tool_call
from stoiquent.llm.reasoning import extract_reasoning
from stoiquent.models import Message, StreamChunk, ToolCall
from stoiquent.sandbox.policy import default_policy

logger = logging.getLogger(__name__)

OnChunkCallback = Callable[[StreamChunk], Coroutine[Any, Any, None]]


async def run_agent_loop(
    session: Session,
    user_message: str,
    on_chunk: OnChunkCallback,
) -> None:
    session.messages.append(Message(role="user", content=user_message))

    for _iteration in range(session.iteration_limit):
        messages, tools = build_messages(session)

        raw_content = ""
        api_reasoning = ""
        tool_calls_accum: list[dict[str, Any]] = []

        try:
            async for chunk in session.provider.stream(messages, tools=tools):
                if chunk.content_delta:
                    raw_content += chunk.content_delta
                if chunk.reasoning_delta:
                    api_reasoning += chunk.reasoning_delta
                if chunk.tool_calls_delta:
                    _accumulate_tool_calls(tool_calls_accum, chunk.tool_calls_delta)
                await on_chunk(chunk)
        finally:
            parsed_tool_calls = _parse_tool_calls(tool_calls_accum)
            if raw_content or api_reasoning or parsed_tool_calls:
                if api_reasoning:
                    final_reasoning: str | None = api_reasoning
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
                        tool_calls=parsed_tool_calls or None,
                    )
                )

        if not parsed_tool_calls:
            return

        if session.catalog is None or session.sandbox is None:
            return

        policy = session.sandbox_policy or default_policy()
        for tc in parsed_tool_calls:
            result = await dispatch_tool_call(
                tc, session.catalog, session.sandbox, policy, session.tool_timeout,
            )
            session.messages.append(
                Message(role="tool", content=result, tool_call_id=tc.id)
            )

    logger.warning("Agent loop reached iteration limit (%d)", session.iteration_limit)


def _accumulate_tool_calls(
    accum: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> None:
    """Accumulate incremental tool call deltas into complete tool calls."""
    for delta in deltas:
        index = delta.get("index", 0)
        while len(accum) <= index:
            accum.append({"id": "", "function": {"name": "", "arguments": ""}})

        entry = accum[index]
        if "id" in delta and delta["id"]:
            entry["id"] = delta["id"]
        func_delta = delta.get("function", {})
        if "name" in func_delta and func_delta["name"]:
            if not entry["function"]["name"]:
                entry["function"]["name"] = func_delta["name"]
            else:
                entry["function"]["name"] += func_delta["name"]
        if "arguments" in func_delta:
            entry["function"]["arguments"] += func_delta["arguments"]


def _parse_tool_calls(accum: list[dict[str, Any]]) -> list[ToolCall]:
    """Parse accumulated tool call data into ToolCall objects."""
    result = []
    for entry in accum:
        call_id = entry.get("id", "")
        func = entry.get("function", {})
        name = func.get("name", "")
        args_str = func.get("arguments", "")

        if not call_id or not name:
            continue

        try:
            arguments = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in tool call arguments: %s", args_str[:200])
            arguments = {}

        result.append(ToolCall(id=call_id, name=name, arguments=arguments))
    return result
