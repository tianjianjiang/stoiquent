from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from stoiquent.agent.loop import (
    OnChunkCallback,
    _accumulate_tool_calls,
    _parse_tool_calls,
    run_agent_loop,
)
from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef
from tests.conftest import FakeProvider


async def _async_noop(_chunk: StreamChunk) -> None:
    pass


def _async_append(target: list[StreamChunk]) -> OnChunkCallback:
    async def _cb(chunk: StreamChunk) -> None:
        target.append(chunk)
    return _cb


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


def test_accumulate_tool_calls_single_delta() -> None:
    accum: list[dict] = []
    _accumulate_tool_calls(accum, [
        {"index": 0, "id": "call_1", "function": {"name": "greet", "arguments": '{"na'}},
    ])
    _accumulate_tool_calls(accum, [
        {"index": 0, "function": {"arguments": 'me":"A"}'}},
    ])
    assert len(accum) == 1
    assert accum[0]["id"] == "call_1"
    assert accum[0]["function"]["name"] == "greet"
    assert accum[0]["function"]["arguments"] == '{"name":"A"}'


def test_parse_tool_calls_valid() -> None:
    accum = [
        {"id": "call_1", "function": {"name": "greet", "arguments": '{"name":"Alice"}'}},
    ]
    result = _parse_tool_calls(accum)
    assert len(result) == 1
    assert result[0].id == "call_1"
    assert result[0].name == "greet"
    assert result[0].arguments == {"name": "Alice"}


def test_parse_tool_calls_skips_incomplete() -> None:
    accum = [
        {"id": "", "function": {"name": "greet", "arguments": "{}"}},
        {"id": "call_2", "function": {"name": "", "arguments": "{}"}},
    ]
    assert _parse_tool_calls(accum) == []


def test_parse_tool_calls_skips_bad_json() -> None:
    accum = [
        {"id": "call_1", "function": {"name": "test", "arguments": "not json"}},
    ]
    result = _parse_tool_calls(accum)
    assert result == []


@pytest.mark.asyncio
async def test_should_dispatch_tool_calls_and_loop(tmp_path: Path) -> None:
    """Full integration: LLM returns tool call, dispatch runs, LLM gets result."""
    skill_dir = tmp_path / "hello"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "greet.py").write_text(
        "#!/usr/bin/env python3\nimport sys, json\n"
        "args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}\n"
        "print(f\"Hello, {args.get('name', 'World')}!\")\n"
    )

    skill = Skill(
        meta=SkillMeta(
            name="hello",
            description="Greeting",
            tools=[SkillToolDef(name="greet", description="Greet")],
        ),
        path=skill_dir,
        active=True,
    )
    catalog = SkillCatalog({"hello": skill})
    sandbox = NoopBackend()

    call_count = 0

    @dataclass
    class ToolThenContentProvider:
        async def stream(
            self,
            messages: list[Message],
            tools: list[dict] | None = None,
        ) -> AsyncIterator[StreamChunk]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamChunk(
                    tool_calls_delta=[{
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "greet",
                            "arguments": json.dumps({"name": "Alice"}),
                        },
                    }],
                    finish_reason="tool_calls",
                )
            else:
                yield StreamChunk(content_delta="Done greeting!")
                yield StreamChunk(finish_reason="stop")

    session = Session(
        provider=ToolThenContentProvider(),
        catalog=catalog,
        sandbox=sandbox,
        tool_timeout=10.0,
    )
    await run_agent_loop(session, "Greet Alice", _async_noop)

    assert call_count == 2
    assert any(m.role == "tool" for m in session.messages)
    tool_msg = next(m for m in session.messages if m.role == "tool")
    assert "Hello, Alice!" in tool_msg.content
    assert session.messages[-1].role == "assistant"
    assert session.messages[-1].content == "Done greeting!"


@pytest.mark.asyncio
async def test_should_not_dispatch_without_catalog() -> None:
    """Without catalog/sandbox, tool calls are recorded but not dispatched."""
    provider = FakeProvider(
        chunks=[
            StreamChunk(
                tool_calls_delta=[{
                    "index": 0,
                    "id": "call_1",
                    "function": {"name": "test", "arguments": "{}"},
                }],
                finish_reason="tool_calls",
            ),
        ]
    )
    session = Session(provider=provider)
    await run_agent_loop(session, "Hi", _async_noop)

    # assistant with tool_calls + tool error messages (catalog not configured)
    assert len(session.messages) >= 3
    assert session.messages[1].tool_calls is not None
    assert session.messages[1].tool_calls[0].name == "test"
    # Should have a tool result error message since catalog is None
    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "not available" in tool_msgs[0].content


@pytest.mark.asyncio
async def test_should_stop_at_iteration_limit(tmp_path: Path) -> None:
    """Verify the loop terminates when iteration limit is reached."""
    skill_dir = tmp_path / "loop"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "echo.py").write_text(
        "#!/usr/bin/env python3\nprint('ok')\n"
    )

    skill = Skill(
        meta=SkillMeta(
            name="loop",
            description="Looping skill",
            tools=[SkillToolDef(name="echo", description="Echo")],
        ),
        path=skill_dir,
        active=True,
    )
    catalog = SkillCatalog({"loop": skill})
    sandbox = NoopBackend()

    @dataclass
    class AlwaysToolCallProvider:
        async def stream(
            self,
            messages: list[Message],
            tools: list[dict] | None = None,
        ) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(
                tool_calls_delta=[{
                    "index": 0,
                    "id": f"call_{len(messages)}",
                    "function": {"name": "echo", "arguments": "{}"},
                }],
                finish_reason="tool_calls",
            )

    session = Session(
        provider=AlwaysToolCallProvider(),
        catalog=catalog,
        sandbox=sandbox,
        iteration_limit=2,
        tool_timeout=10.0,
    )
    await run_agent_loop(session, "Loop forever", _async_noop)

    # Should have: user + (assistant+tool_call, tool_result) x 2
    assistant_msgs = [m for m in session.messages if m.role == "assistant"]
    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert len(assistant_msgs) == 2
    assert len(tool_msgs) == 2
