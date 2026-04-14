from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import StreamChunk
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.sandbox.policy import default_policy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef

from tests.integration.conftest import skip_no_model, skip_no_ollama

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


def _make_tool_session(provider: OpenAICompatProvider) -> Session:
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


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
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
@pytest.mark.asyncio
async def test_should_pass_arguments_to_tool(
    provider: OpenAICompatProvider,
) -> None:
    """Verify the LLM passes correct arguments through to the script."""
    session = _make_tool_session(provider)

    async def noop(_chunk: StreamChunk) -> None:
        pass

    await run_agent_loop(
        session,
        "Use the greet tool to greet Bob. You must call the greet tool with name Bob.",
        noop,
    )

    tool_msgs = [m for m in session.messages if m.role == "tool"]
    assert len(tool_msgs) >= 1, (
        f"Expected tool message, got roles: {[m.role for m in session.messages]}"
    )
    assert any("Hello, Bob!" in (m.content or "") for m in tool_msgs)
