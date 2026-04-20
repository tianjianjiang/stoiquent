"""Integration tests for MCP bridge with real echo server."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import StreamChunk
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.sandbox.policy import default_policy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.mcp_bridge import MCPBridge
from stoiquent.skills.models import MCPServerDef, Skill, SkillMeta, SkillToolDef

from tests.conftest import FakeToolCallingProvider, async_noop, tool_call_script
from tests.integration.conftest import skip_no_model, skip_no_ollama

ECHO_SERVER = str(
    Path(__file__).resolve().parents[1] / "fixtures" / "mcp_servers" / "echo_server.py"
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_start_discover_call_and_stop_mcp_server() -> None:
    """Full lifecycle: start server, discover tools, call tool, stop."""
    bridge = MCPBridge()
    server_def = MCPServerDef(command=sys.executable, args=[ECHO_SERVER])

    try:
        server_id = await bridge.start_server(server_def)

        tools = bridge.get_tools(server_id)
        tool_names = {t["function"]["name"] for t in tools}
        assert "echo" in tool_names
        assert "add" in tool_names

        echo_result = await bridge.call_tool(server_id, "echo", {"message": "integration test"})
        assert "Echo: integration test" in echo_result

        add_result = await bridge.call_tool(server_id, "add", {"a": 3, "b": 4})
        assert "7" in add_result
    finally:
        await bridge.stop_all()


def _echo_skill() -> Skill:
    """Shared Skill fixture describing the MCP echo server's single ``echo``
    tool; used by both the Ollama-backed and deterministic MCP-routing tests."""
    return Skill(
        meta=SkillMeta(
            name="echo-skill",
            description="Skill backed by MCP echo server",
            tools=[
                SkillToolDef(
                    name="echo",
                    description="Echo back a message. Takes a 'message' string parameter.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Message to echo"},
                        },
                        "required": ["message"],
                    },
                ),
            ],
        ),
        path=Path("/fake"),
        instructions="Use the echo tool when asked to echo something.",
        active=True,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_route_mcp_tool_call_deterministic() -> None:
    """Deterministic counterpart of the Ollama-backed test below — still
    exercises the MCP subprocess, stdio transport, and bridge routing;
    only the LLM source is swapped for a scripted provider."""
    bridge = MCPBridge()
    server_def = MCPServerDef(command=sys.executable, args=[ECHO_SERVER])
    provider = FakeToolCallingProvider(
        scripts=tool_call_script(
            tool_name="echo",
            arguments={"message": "hello from deterministic test"},
            final_reply="Done.",
            call_id="call_echo_1",
        )
    )

    try:
        await bridge.start_server(server_def)
        session = Session(
            provider=provider,
            catalog=SkillCatalog({"echo-skill": _echo_skill()}),
            sandbox=NoopBackend(),
            mcp_bridge=bridge,
            sandbox_policy=default_policy(),
            iteration_limit=5,
            tool_timeout=30.0,
        )

        await run_agent_loop(
            session,
            "Echo 'hello from deterministic test'.",
            async_noop,
        )

        assert provider.call_count == 2
        tool_msgs = [m for m in session.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "Echo: hello from deterministic test" in (tool_msgs[0].content or "")
        assert session.messages[-1].content == "Done."
    finally:
        await bridge.stop_all()


@skip_no_ollama
@skip_no_model
@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_should_route_mcp_tool_call_from_llm(
    provider: OpenAICompatProvider,
) -> None:
    """End-to-end: LLM calls an MCP tool, bridge forwards to echo server."""
    bridge = MCPBridge()
    server_def = MCPServerDef(command=sys.executable, args=[ECHO_SERVER])

    try:
        await bridge.start_server(server_def)
        session = Session(
            provider=provider,
            catalog=SkillCatalog({"echo-skill": _echo_skill()}),
            sandbox=NoopBackend(),
            mcp_bridge=bridge,
            sandbox_policy=default_policy(),
            iteration_limit=5,
            tool_timeout=30.0,
        )

        chunks: list[StreamChunk] = []

        async def on_chunk(chunk: StreamChunk) -> None:
            chunks.append(chunk)

        await run_agent_loop(
            session,
            "Use the echo tool to echo the message 'hello from integration test'. You must call the echo tool.",
            on_chunk,
        )

        tool_msgs = [m for m in session.messages if m.role == "tool"]
        assert len(tool_msgs) >= 1, (
            f"Expected tool message, got roles: {[m.role for m in session.messages]}"
        )
        assert any("Echo:" in (m.content or "") for m in tool_msgs)
    finally:
        await bridge.stop_all()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_handle_start_server_failure() -> None:
    bridge = MCPBridge()
    bad_def = MCPServerDef(command="/nonexistent/binary/xyz", args=[])
    with pytest.raises(Exception):
        await bridge.start_server(bad_def)
    assert bridge.server_ids == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_handle_call_to_unknown_server() -> None:
    bridge = MCPBridge()
    result = await bridge.call_tool("nonexistent_id", "echo", {"message": "hi"})
    assert "not found" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_find_tools_across_servers() -> None:
    bridge = MCPBridge()
    server_def = MCPServerDef(command=sys.executable, args=[ECHO_SERVER])
    try:
        sid = await bridge.start_server(server_def)

        all_tools = bridge.get_tools()
        assert len(all_tools) >= 2

        echo_server = bridge.find_server_for_tool("echo")
        assert echo_server == sid

        unknown = bridge.find_server_for_tool("nonexistent_tool")
        assert unknown is None

        server_tools = bridge.get_tools(sid)
        assert len(server_tools) >= 1
    finally:
        await bridge.stop_all()
