from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.llm.provider import LLMProvider
from stoiquent.models import StreamChunk
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.sandbox.policy import default_policy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef

from tests.conftest import FakeToolCallingProvider, async_noop, tool_call_script
from tests.integration.conftest import skip_no_model, skip_no_ollama

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


def _make_tool_session(provider: LLMProvider) -> Session:
    """Create a session with the hello-world skill activated."""
    skill = Skill(
        meta=SkillMeta(
            name="hello-world",
            description="A simple greeting skill for testing",
            tools=[
                SkillToolDef(
                    name="greet",
                    description="Greet someone by name. Takes a JSON argument with a 'name' field.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "The name of the person to greet",
                            }
                        },
                        "required": ["name"],
                    },
                )
            ],
        ),
        path=FIXTURES / "hello-world",
        instructions="Use the greet tool when asked to greet someone.",
        active=True,
    )
    catalog = SkillCatalog({"hello-world": skill})
    sandbox = NoopBackend()

    return Session(
        provider=provider,
        catalog=catalog,
        sandbox=sandbox,
        sandbox_policy=default_policy(),
        iteration_limit=5,
        tool_timeout=30.0,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_tool_call_round_trip_deterministic() -> None:
    """Deterministic counterpart of the Ollama-backed test below — exercises
    the sandbox, message-accumulation wiring, and that ``build_messages``
    feeds the second turn with the injected tool result."""
    provider = FakeToolCallingProvider(
        scripts=tool_call_script(
            tool_name="greet",
            arguments={"name": "Alice"},
            final_reply="Done.",
        )
    )
    session = _make_tool_session(provider)
    chunks: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        chunks.append(chunk)

    await run_agent_loop(
        session,
        "Use the greet tool to greet Alice.",
        on_chunk,
    )

    assert provider.call_count == 2, "Expected exactly two LLM turns"
    roles = [m.role for m in session.messages]
    assert roles == ["user", "assistant", "tool", "assistant"], roles

    assistant_with_tools = next(
        m for m in session.messages if m.role == "assistant" and m.tool_calls
    )
    assert assistant_with_tools.tool_calls is not None
    assert assistant_with_tools.tool_calls[0].name == "greet"
    assert assistant_with_tools.tool_calls[0].arguments == {"name": "Alice"}

    tool_msg = next(m for m in session.messages if m.role == "tool")
    assert "Hello, Alice!" in (tool_msg.content or "")

    assert session.messages[-1].role == "assistant"
    assert session.messages[-1].content == "Done."

    # on_chunk must observe the synthetic tool_call_start and tool_call_result
    # emitted by the loop around the sandbox dispatch.
    assert any(c.tool_call_start is not None for c in chunks)
    assert any(c.tool_call_result is not None for c in chunks)

    # Turn 2 must receive the injected tool result, not just the original
    # user prompt — guards against build_messages regressions that would
    # pass the Ollama-gated test only because a real LLM would re-call
    # the tool. build_messages prepends a system message; the remainder
    # must be the accumulated session history with the tool result
    # injected between the assistant's tool_calls and the next turn.
    turn2_messages = provider.calls[1]["messages"]
    turn2_roles = [m.role for m in turn2_messages]
    assert turn2_roles == ["system", "user", "assistant", "tool"], turn2_roles
    tool_turn2 = turn2_messages[3]
    assert tool_turn2.tool_call_id == "call_1"
    assistant_turn2 = turn2_messages[2]
    assert assistant_turn2.tool_calls is not None
    assert assistant_turn2.tool_calls[0].id == "call_1"

    # Tools catalog must be present on both turns and must actually name
    # the `greet` tool — a truthy check would pass on malformed schemas.
    assert provider.calls[0]["tools"] is not None
    assert any(
        t.get("function", {}).get("name") == "greet"
        for t in provider.calls[0]["tools"]
    )
    assert provider.calls[1]["tools"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_execute_tool_call_with_fragmented_deltas() -> None:
    """Reassembly regressions only surface when ``function.arguments`` is
    fragmented across chunks the way real providers stream. Scripts this
    shape explicitly alongside an assistant preface and asserts the loop
    still produces a single ``greet`` call with intact arguments."""
    turn1: list[StreamChunk] = [
        StreamChunk(content_delta="Let me call the tool."),
        StreamChunk(
            tool_calls_delta=[
                {
                    "index": 0,
                    "id": "call_fragmented",
                    "function": {"name": "greet", "arguments": '{"na'},
                }
            ]
        ),
        StreamChunk(
            tool_calls_delta=[
                {"index": 0, "function": {"arguments": 'me": "Bob"}'}}
            ],
            finish_reason="tool_calls",
        ),
    ]
    turn2 = [
        StreamChunk(content_delta="Done."),
        StreamChunk(finish_reason="stop"),
    ]
    provider = FakeToolCallingProvider(scripts=[turn1, turn2])
    session = _make_tool_session(provider)

    await run_agent_loop(session, "Greet Bob.", async_noop)

    assistant_with_tools = next(
        m for m in session.messages if m.role == "assistant" and m.tool_calls
    )
    assert assistant_with_tools.tool_calls is not None
    assert assistant_with_tools.tool_calls[0].id == "call_fragmented"
    assert assistant_with_tools.tool_calls[0].arguments == {"name": "Bob"}
    # Preface content must survive into the assistant history somewhere —
    # assert on the aggregate rather than the specific layout so a future
    # split of preface into its own assistant turn still passes.
    assistant_text = "".join(
        m.content or "" for m in session.messages if m.role == "assistant"
    )
    assert "Let me call the tool." in assistant_text
    tool_msg = next(m for m in session.messages if m.role == "tool")
    assert "Hello, Bob!" in (tool_msg.content or "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fake_provider_raises_on_overrun_through_loop() -> None:
    """Loud-fail contract: when ``run_agent_loop`` needs more turns than
    scripted, the fake's IndexError propagates out of the loop — so a
    future refactor that swallowed provider exceptions would be caught."""
    under_scripted: list[list[StreamChunk]] = [
        [
            StreamChunk(
                tool_calls_delta=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "greet",
                            "arguments": '{"name": "Alice"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
        ],
    ]
    # Script two tool-calling turns so the loop requests a third
    # stream() call — that 3rd call has no script and raises
    # IndexError("turn 2 requested") (0-indexed, i.e. the 3rd call).
    under_scripted.append(
        [
            StreamChunk(
                tool_calls_delta=[
                    {
                        "index": 0,
                        "id": "call_2",
                        "function": {
                            "name": "greet",
                            "arguments": '{"name": "Bob"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    provider = FakeToolCallingProvider(scripts=under_scripted)
    session = _make_tool_session(provider)
    with pytest.raises(IndexError, match="turn 2 requested"):
        await run_agent_loop(session, "Greet.", async_noop)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_dispatch_parallel_tool_calls() -> None:
    """Two tool calls in the same assistant turn must each dispatch and
    each appear as a ``role=tool`` message with its own tool_call_id.
    Guards the ``while len(accum) <= index`` branch in
    ``_accumulate_tool_calls`` and the per-call dispatch loop."""
    turn1 = [
        StreamChunk(
            tool_calls_delta=[
                {
                    "index": 0,
                    "id": "call_a",
                    "function": {"name": "greet", "arguments": '{"name": "Alice"}'},
                },
                {
                    "index": 1,
                    "id": "call_b",
                    "function": {"name": "greet", "arguments": '{"name": "Bob"}'},
                },
            ],
            finish_reason="tool_calls",
        )
    ]
    turn2 = [
        StreamChunk(content_delta="Greeted both."),
        StreamChunk(finish_reason="stop"),
    ]
    provider = FakeToolCallingProvider(scripts=[turn1, turn2])
    session = _make_tool_session(provider)
    chunks: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        chunks.append(chunk)

    await run_agent_loop(session, "Greet Alice and Bob.", on_chunk)

    assistant = next(
        m for m in session.messages if m.role == "assistant" and m.tool_calls
    )
    assert assistant.tool_calls is not None
    assert [tc.id for tc in assistant.tool_calls] == ["call_a", "call_b"]

    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["call_a", "call_b"]
    assert "Hello, Alice!" in (tool_msgs[0].content or "")
    assert "Hello, Bob!" in (tool_msgs[1].content or "")

    starts = [c.tool_call_start for c in chunks if c.tool_call_start is not None]
    assert [tc.id for tc in starts] == ["call_a", "call_b"]
    results = [c.tool_call_result for c in chunks if c.tool_call_result is not None]
    assert [r.tool_call_id for r in results] == ["call_a", "call_b"]

    turn2_roles = [m.role for m in provider.calls[1]["messages"]]
    assert turn2_roles == ["system", "user", "assistant", "tool", "tool"], turn2_roles
    turn2_tool_ids = [
        m.tool_call_id for m in provider.calls[1]["messages"] if m.role == "tool"
    ]
    assert turn2_tool_ids == ["call_a", "call_b"]


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_execute_tool_call_round_trip(
    provider: OpenAICompatProvider,
) -> None:
    """Full flow: user asks to greet -> LLM tool call -> sandbox -> result -> final answer."""
    session = _make_tool_session(provider)
    chunks: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        chunks.append(chunk)

    await run_agent_loop(
        session,
        "Use the greet tool to greet Alice. Do not write the greeting yourself, you must use the tool.",
        on_chunk,
    )

    # Should have: user, assistant (with tool_calls), tool (result), assistant (final)
    assert len(session.messages) >= 4, (
        f"Expected at least 4 messages (user, assistant+tool_call, tool, assistant), "
        f"got {len(session.messages)}: {[m.role for m in session.messages]}"
    )

    # Find the tool result message
    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert len(tool_msgs) >= 1, (
        f"Expected at least one tool message, got roles: {[m.role for m in session.messages]}"
    )
    assert any("Hello, Alice!" in (m.content or "") for m in tool_msgs)

    # The assistant should have made a tool call
    assistant_with_tools = [
        m for m in session.messages
        if m.role == "assistant" and m.tool_calls
    ]
    assert len(assistant_with_tools) >= 1
    assert any(tc.name == "greet" for tc in assistant_with_tools[0].tool_calls)

    # Final message should be assistant with content (the response after tool result)
    assert session.messages[-1].role == "assistant"
    assert session.messages[-1].content is not None


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_pass_arguments_to_tool(
    provider: OpenAICompatProvider,
) -> None:
    """Verify the LLM passes correct arguments through to the script."""
    session = _make_tool_session(provider)

    await run_agent_loop(
        session,
        "Use the greet tool to greet Bob. You must call the greet tool with name Bob.",
        async_noop,
    )

    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert len(tool_msgs) >= 1, (
        f"Expected tool message, got roles: {[m.role for m in session.messages]}"
    )
    assert any("Hello, Bob!" in (m.content or "") for m in tool_msgs)


def _make_apple_tool_session(provider: OpenAICompatProvider) -> Session | None:
    """Create a session with Apple Containers backend. Returns None if unavailable."""
    import os
    import shutil

    from stoiquent.sandbox.apple import AppleContainersBackend

    container_path = shutil.which("container") or "/opt/local/bin/container"
    if not os.path.isfile(container_path):
        return None

    skill = Skill(
        meta=SkillMeta(
            name="hello-world",
            description="A simple greeting skill for testing",
            tools=[
                SkillToolDef(
                    name="greet",
                    description="Greet someone by name.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Name to greet"}
                        },
                        "required": ["name"],
                    },
                )
            ],
        ),
        path=FIXTURES / "hello-world",
        instructions="Use the greet tool when asked to greet someone.",
        active=True,
    )
    catalog = SkillCatalog({"hello-world": skill})
    sandbox = AppleContainersBackend(container_path, image="python:3.12-slim")

    return Session(
        provider=provider,
        catalog=catalog,
        sandbox=sandbox,
        sandbox_policy=default_policy(),
        iteration_limit=5,
        tool_timeout=60.0,
    )


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_tool_execution_with_apple_containers(
    provider: OpenAICompatProvider,
) -> None:
    """Tool dispatch through real Apple Containers VM sandbox."""
    session = _make_apple_tool_session(provider)
    if session is None:
        pytest.skip("Apple Containers not available")

    await run_agent_loop(
        session,
        "Use the greet tool to greet Alice. You must call the greet tool.",
        async_noop,
    )

    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert len(tool_msgs) >= 1, (
        f"Expected tool message, got roles: {[m.role for m in session.messages]}"
    )
    assert any("Hello, Alice!" in (m.content or "") for m in tool_msgs)
