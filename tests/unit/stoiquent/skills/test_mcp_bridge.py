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


@pytest.fixture(autouse=True)
def _reset_pgrep_warning_flag():
    # Module-global one-shot flag persists across the interpreter; resetting
    # per test avoids cross-test coupling where the first test that
    # exercises a pgrep-unusable path silences warnings for all later tests.
    import stoiquent.skills.mcp_bridge as bridge_mod
    bridge_mod._pgrep_unusable_warned = False
    yield
    bridge_mod._pgrep_unusable_warned = False


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
    # Spawn-then-wait gives a guaranteed-exited PID without signalling init,
    # which would be unsafe under root (e.g., container dev/CI environments).
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert await _reap_pgroup(proc.pid, timeout=0.05) is True


@pytest.mark.asyncio
async def test_reap_pgroup_refuses_to_signal_sentinel_pids() -> None:
    # Guards against `_direct_children()` ever leaking 0/1 into `pids`,
    # which would otherwise SIGKILL our own process group / init.
    assert await _reap_pgroup(0, timeout=0.05) is True
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


@pytest.mark.asyncio
async def test_reap_pgroup_uses_kill_when_not_session_leader() -> None:
    # Spawn without start_new_session so child shares parent's pgid;
    # _reap_pgroup must detect pgid != pid and use os.kill, not os.killpg
    # (which would target the test runner's group).
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    assert os.getpgid(proc.pid) != proc.pid, "child unexpectedly is its own session leader"
    try:
        result = await _reap_pgroup(proc.pid, timeout=0.2)
        assert result is False
        proc.wait(timeout=2.0)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:  # pragma: no cover
            proc.kill()
            proc.wait()


def test_direct_children_handles_no_matches(monkeypatch) -> None:
    # pgrep returns rc=1 with empty stdout when there are no children.
    import stoiquent.skills.mcp_bridge as bridge_mod
    import types

    def _fake_run(*_args, **_kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(bridge_mod.subprocess, "run", _fake_run)
    assert bridge_mod._direct_children() == set()


def test_direct_children_parses_pgrep_output(monkeypatch) -> None:
    import stoiquent.skills.mcp_bridge as bridge_mod
    import types

    def _fake_run(*_args, **_kwargs):
        return types.SimpleNamespace(returncode=0, stdout="123\n456\n", stderr="")

    monkeypatch.setattr(bridge_mod.subprocess, "run", _fake_run)
    assert bridge_mod._direct_children() == {123, 456}


@pytest.mark.asyncio
async def test_stop_server_logs_aclose_exception_at_error(monkeypatch, caplog) -> None:
    bridge = MCPBridge()
    sid = await bridge.start_server(
        MCPServerDef(command=sys.executable, args=[ECHO_SERVER])
    )

    async def _raising_aclose() -> None:
        raise RuntimeError("simulated aclose failure")

    monkeypatch.setattr(bridge._servers[sid].exit_stack, "aclose", _raising_aclose)
    with caplog.at_level("ERROR", logger="stoiquent.skills.mcp_bridge"):
        await bridge.stop_server(sid)
    # R2's narrowed exception split must surface real teardown failures at
    # ERROR with traceback, not bury them at DEBUG.
    assert any(
        "cleanup failed" in r.message and r.levelname == "ERROR"
        for r in caplog.records
    ), f"expected ERROR log; got {[(r.levelname, r.message) for r in caplog.records]}"
    assert bridge.server_ids == []


@pytest.mark.asyncio
async def test_stop_server_logs_aclose_cancelled_at_debug(monkeypatch, caplog) -> None:
    bridge = MCPBridge()
    sid = await bridge.start_server(
        MCPServerDef(command=sys.executable, args=[ECHO_SERVER])
    )

    import asyncio as _asyncio

    async def _cancelled_aclose() -> None:
        raise _asyncio.CancelledError()

    monkeypatch.setattr(bridge._servers[sid].exit_stack, "aclose", _cancelled_aclose)
    with caplog.at_level("DEBUG", logger="stoiquent.skills.mcp_bridge"):
        await bridge.stop_server(sid)
    assert any(
        "cleanup cancelled" in r.message and r.levelname == "DEBUG"
        for r in caplog.records
    )
    # No ERROR log: CancelledError is the expected, benign teardown signal.
    assert not any(r.levelname == "ERROR" for r in caplog.records)
    assert bridge.server_ids == []


@pytest.mark.asyncio
async def test_stop_server_logs_when_reap_raises(monkeypatch, caplog) -> None:
    import stoiquent.skills.mcp_bridge as bridge_mod

    bridge = MCPBridge()
    sid = await bridge.start_server(
        MCPServerDef(command=sys.executable, args=[ECHO_SERVER])
    )

    async def _boom(_pid: int, timeout: float = 5.0) -> bool:
        raise RuntimeError("simulated reap failure")

    monkeypatch.setattr(bridge_mod, "_reap_pgroup", _boom)
    with caplog.at_level("ERROR", logger="stoiquent.skills.mcp_bridge"):
        await bridge.stop_server(sid)
    # Reap exception should be logged with server context, not propagated.
    assert any("MCPBridge reap raised" in r.message for r in caplog.records)
    assert bridge.server_ids == []


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
    if initial_fd_count < 0:  # pragma: no cover
        pytest.skip("FD introspection unavailable on this platform")
    leaked_pids: list[int] = []

    for _ in range(100):
        bridge = MCPBridge()
        sid = await bridge.start_server(server_def)
        tracked = bridge._servers[sid].pids
        # Loud failure if PID tracking ever silently degrades to set();
        # otherwise the leak-detection assertion would vacuously pass.
        assert tracked, "bridge did not capture spawned PIDs; reap path unverifiable"
        await bridge.stop_all()
        for pid in tracked:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                # ProcessLookupError = gone; PermissionError = PID recycled
                # to another UID's process (not our leak).
                continue
            leaked_pids.append(pid)

    assert leaked_pids == [], f"Subprocess leak across 100 cycles: {leaked_pids}"

    final_fd_count = _count_open_fds()
    # Allow small fluctuation (logging handlers, etc.); guard against O(N) leak.
    assert final_fd_count - initial_fd_count < 10, (
        f"FD leak across 100 cycles: {initial_fd_count} -> {final_fd_count}"
    )
