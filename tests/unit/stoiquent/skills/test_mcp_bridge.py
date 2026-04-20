from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from stoiquent.skills.mcp_bridge import MCPBridge, _mcp_tool_to_openai, _reap_pgroup
from stoiquent.skills.models import MCPServerDef

ECHO_SERVER = str(
    Path(__file__).resolve().parents[3] / "fixtures" / "mcp_servers" / "echo_server.py"
)


@dataclass
class FakeMCPTool:
    """Mimics the MCP SDK tool object shape without importing MCP types."""
    name: str
    description: str | None = ""
    inputSchema: dict[str, Any] | None = field(
        default_factory=lambda: {"type": "object", "properties": {"message": {"type": "string"}}}
    )


def test_mcp_tool_to_openai_format() -> None:
    tool = FakeMCPTool("echo", "Echo back a message")
    result = _mcp_tool_to_openai(tool, "srv_1")
    assert result["type"] == "function"
    assert result["function"]["name"] == "echo"
    assert result["function"]["description"] == "Echo back a message"
    assert result["_mcp_server_id"] == "srv_1"


def test_mcp_tool_to_openai_with_empty_description() -> None:
    tool = FakeMCPTool("echo")
    tool.description = None
    result = _mcp_tool_to_openai(tool, "srv_1")
    assert result["function"]["description"] == ""


def test_mcp_tool_to_openai_with_no_schema() -> None:
    tool = FakeMCPTool("echo")
    tool.inputSchema = None
    result = _mcp_tool_to_openai(tool, "srv_1")
    assert result["function"]["parameters"] == {"type": "object", "properties": {}}


@pytest.mark.asyncio
async def test_bridge_starts_empty() -> None:
    bridge = MCPBridge()
    assert bridge.server_ids == []
    assert bridge.get_tools() == []
    assert bridge.find_server_for_tool("anything") is None


@pytest.mark.asyncio
async def test_bridge_stop_nonexistent_server() -> None:
    bridge = MCPBridge()
    await bridge.stop_server("nonexistent")


@pytest.mark.asyncio
async def test_bridge_call_tool_unknown_server() -> None:
    bridge = MCPBridge()
    result = await bridge.call_tool("nonexistent", "echo", {"message": "hi"})
    assert "not found" in result


@pytest.mark.asyncio
async def test_bridge_start_and_stop_real_server() -> None:
    """Integration-style test using the real echo MCP server."""
    bridge = MCPBridge()
    server_def = MCPServerDef(
        command=sys.executable,
        args=[ECHO_SERVER],
    )
    server_id = await bridge.start_server(server_def)

    assert server_id in bridge.server_ids
    tools = bridge.get_tools(server_id)
    assert len(tools) >= 1
    tool_names = [t["function"]["name"] for t in tools]
    assert "echo" in tool_names

    await bridge.stop_server(server_id)
    assert server_id not in bridge.server_ids


@pytest.mark.asyncio
async def test_bridge_call_tool_real_server() -> None:
    """Call a tool on the real echo MCP server."""
    bridge = MCPBridge()
    server_def = MCPServerDef(
        command=sys.executable,
        args=[ECHO_SERVER],
    )
    server_id = await bridge.start_server(server_def)

    result = await bridge.call_tool(server_id, "echo", {"message": "hello"})
    assert "Echo: hello" in result

    await bridge.stop_all()
    assert bridge.server_ids == []


@pytest.mark.asyncio
async def test_bridge_find_server_for_tool() -> None:
    bridge = MCPBridge()
    server_def = MCPServerDef(
        command=sys.executable,
        args=[ECHO_SERVER],
    )
    server_id = await bridge.start_server(server_def)

    found = bridge.find_server_for_tool("echo")
    assert found == server_id

    assert bridge.find_server_for_tool("nonexistent") is None

    await bridge.stop_all()


@pytest.mark.asyncio
async def test_bridge_stop_all() -> None:
    bridge = MCPBridge()
    server_def = MCPServerDef(
        command=sys.executable,
        args=[ECHO_SERVER],
    )
    await bridge.start_server(server_def)
    await bridge.start_server(server_def)
    assert len(bridge.server_ids) == 2

    await bridge.stop_all()
    assert bridge.server_ids == []


@pytest.mark.asyncio
async def test_bridge_get_tools_all_servers() -> None:
    bridge = MCPBridge()
    server_def = MCPServerDef(
        command=sys.executable,
        args=[ECHO_SERVER],
    )
    await bridge.start_server(server_def)

    all_tools = bridge.get_tools()
    assert len(all_tools) >= 2
    names = {t["function"]["name"] for t in all_tools}
    assert "echo" in names
    assert "add" in names

    await bridge.stop_all()


@pytest.mark.asyncio
async def test_bridge_start_server_failure() -> None:
    bridge = MCPBridge()
    server_def = MCPServerDef(
        command="/nonexistent/binary",
        args=[],
    )
    with pytest.raises(Exception):
        await bridge.start_server(server_def)
    assert bridge.server_ids == []


@pytest.mark.asyncio
async def test_reap_pgroup_returns_true_when_pid_already_gone() -> None:
    # PID 1 (init) is owned by another user; os.kill(_, 0) raises PermissionError,
    # which _reap_pgroup treats as "not ours, stop polling".
    assert await _reap_pgroup(1, timeout=0.05) is True


@pytest.mark.asyncio
async def test_reap_pgroup_force_kills_runaway_subprocess() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        result = await _reap_pgroup(proc.pid, timeout=0.2)
        assert result is False, "SIGKILL fallback should have fired"
        proc.wait(timeout=2.0)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:  # pragma: no cover
            proc.kill()
            proc.wait()


def _count_open_fds() -> int:
    """POSIX-only open-FD count for the current process; -1 if unsupported."""
    pid = os.getpid()
    for path in (f"/proc/{pid}/fd", "/dev/fd"):
        try:
            return len(os.listdir(path))
        except (FileNotFoundError, OSError):
            continue
    return -1  # pragma: no cover


@pytest.mark.asyncio
async def test_bridge_start_stop_tight_loop_no_subprocess_or_fd_leak() -> None:
    """E2 acceptance: 100 start/stop cycles leak no subprocesses or FDs.

    Targets the de-flake plan's 'MCP subprocess stdio race on
    teardown-vs-next-start' root cause; if FDs/processes leak, a
    session-scoped event loop carries dirty state into the next test."""
    server_def = MCPServerDef(command=sys.executable, args=[ECHO_SERVER])

    # Warm up once so first-iteration imports/caches don't skew FD count.
    warmup = MCPBridge()
    await warmup.start_server(server_def)
    await warmup.stop_all()

    initial_fd_count = _count_open_fds()
    leaked_pids: list[int] = []

    for _ in range(100):
        bridge = MCPBridge()
        sid = await bridge.start_server(server_def)
        tracked = bridge._servers[sid].pids
        await bridge.stop_all()
        for pid in tracked:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            leaked_pids.append(pid)

    assert leaked_pids == [], f"Subprocess leak across 100 cycles: {leaked_pids}"

    final_fd_count = _count_open_fds()
    if initial_fd_count >= 0:
        # Allow small fluctuation (logging handlers, etc.); guard against O(N) leak.
        assert final_fd_count - initial_fd_count < 10, (
            f"FD leak across 100 cycles: {initial_fd_count} -> {final_fd_count}"
        )
