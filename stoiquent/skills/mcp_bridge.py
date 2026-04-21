from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import uuid
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from stoiquent.skills.models import MCPServerDef

logger = logging.getLogger(__name__)

_REAP_TIMEOUT_SECONDS = 5.0
_pgrep_unusable_warned = False


def _direct_children() -> set[int]:
    """Direct child PIDs of this process via `pgrep -P`; empty set on failure.

    POSIX-only. When pgrep is missing/erroring, the bridge's reap path
    becomes a no-op for newly-spawned subprocesses; we log once so silent
    degradation is observable in CI."""
    global _pgrep_unusable_warned
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:  # pragma: no cover
        if not _pgrep_unusable_warned:
            logger.warning(
                "MCPBridge cannot enumerate child PIDs via pgrep (%s); "
                "subprocess reap will rely solely on stdio_client teardown.",
                type(e).__name__,
            )
            _pgrep_unusable_warned = True
        return set()
    if result.returncode not in (0, 1):  # 0=found, 1=none, >=2=error
        if not _pgrep_unusable_warned:  # pragma: no cover
            logger.warning(
                "MCPBridge pgrep returned rc=%d; orphan reap disabled.",
                result.returncode,
            )
            _pgrep_unusable_warned = True
        return set()  # pragma: no cover
    return {int(p) for p in result.stdout.split() if p.strip()}


async def _reap_pgroup(pid: int, timeout: float = _REAP_TIMEOUT_SECONDS) -> bool:
    """Belt-and-suspenders reap after stdio_client teardown.

    The MCP stdio_client (via `mcp.os.posix.utilities.terminate_posix_process_tree`)
    already SIGTERM/SIGKILL-escalates internally, but its reap can return
    before the OS releases the PID/FDs, leaving a window where the next
    test sees stale state. Returns True if cleanly gone, False if SIGKILL
    fallback fired (or could not deliver)."""
    if pid <= 1:  # 0 == own pgroup, 1 == init: refuse to signal these
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # PID exists but isn't ours (recycled to another UID); stop polling.
            return True
        await asyncio.sleep(0.05)
    # Prefer killpg (relies on stdio_client's start_new_session=True so
    # pid == pgid); fall back to plain kill if the child escaped its session.
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return True
    target_killpg = pgid == pid
    try:
        if target_killpg:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        logger.error(
            "MCPBridge could not SIGKILL orphan pid=%d (PermissionError); "
            "subprocess may be leaking.",
            pid,
        )
        return False
    logger.warning(
        "MCPBridge force-killed orphan subprocess pid=%d (via %s) after %.1fs",
        pid, "killpg" if target_killpg else "kill", timeout,
    )
    return False


class MCPBridge:
    """Manages connections to MCP servers declared in skill metadata."""

    def __init__(self) -> None:
        self._servers: dict[str, _ServerConnection] = {}

    async def start_server(self, server_def: MCPServerDef) -> str:
        server_id = uuid.uuid4().hex[:8]
        params = StdioServerParameters(
            command=server_def.command,
            args=server_def.args,
            env=server_def.env if server_def.env else None,
        )

        children_before = _direct_children()
        exit_stack = AsyncExitStack()
        try:
            transport = await exit_stack.enter_async_context(
                stdio_client(params)
            )
            read_stream, write_stream = transport
            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            response = await session.list_tools()
            tools = [
                _mcp_tool_to_openai(tool, server_id)
                for tool in response.tools
            ]

            new_pids = frozenset(_direct_children() - children_before)
            conn = _ServerConnection(
                server_id=server_id,
                server_def=server_def,
                session=session,
                exit_stack=exit_stack,
                tools=tools,
                pids=new_pids,
            )
            self._servers[server_id] = conn
            logger.info(
                "Started MCP server '%s' (id=%s) with %d tools",
                server_def.command,
                server_id,
                len(tools),
            )
            return server_id
        except Exception:
            await exit_stack.aclose()
            raise

    def get_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        if server_id is not None:
            conn = self._servers.get(server_id)
            return list(conn.tools) if conn else []
        tools: list[dict[str, Any]] = []
        for conn in self._servers.values():
            tools.extend(conn.tools)
        return tools

    def find_server_for_tool(self, tool_name: str) -> str | None:
        for server_id, conn in self._servers.items():
            for tool in conn.tools:
                if tool["function"]["name"] == tool_name:
                    return server_id
        return None

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        conn = self._servers.get(server_id)
        if conn is None:
            return f"Error: MCP server '{server_id}' not found"

        try:
            result = await conn.session.call_tool(tool_name, arguments)
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                else:
                    parts.append(str(content))
            return "\n".join(parts) if parts else ""
        except (ConnectionError, BrokenPipeError, EOFError) as e:
            logger.error(
                "MCP server '%s' appears dead (tool '%s'): %s",
                server_id, tool_name, e,
            )
            self._servers.pop(server_id, None)
            return f"Error: MCP server for '{tool_name}' is no longer available: {e}"
        except Exception as e:
            logger.exception("MCP tool call '%s' failed on server '%s'", tool_name, server_id)
            return f"Error: MCP tool '{tool_name}' failed: {e}"

    async def stop_server(self, server_id: str) -> None:
        conn = self._servers.pop(server_id, None)
        if conn is None:
            return
        try:
            await conn.exit_stack.aclose()
        except (KeyboardInterrupt, SystemExit):
            raise
        except asyncio.CancelledError:
            # Expected when stopping multiple MCP servers in the same loop task
            logger.debug("MCP server '%s' cleanup cancelled", server_id)
        except Exception:
            # Real teardown failure: don't bury at DEBUG; the reap below
            # depends on aclose having released the subprocess FDs.
            logger.exception("MCP server '%s' cleanup failed", server_id)
        finally:
            if not conn.pids:
                logger.debug(
                    "MCPBridge server '%s' (command=%r) had no tracked PIDs; "
                    "orphan reap skipped (wrapper command or pgrep unavailable).",
                    server_id, conn.server_def.command,
                )
            else:
                for pid in conn.pids:
                    try:
                        if not await _reap_pgroup(pid):
                            logger.warning(
                                "MCPBridge server '%s' (command=%r) required SIGKILL fallback for pid=%d",
                                server_id, conn.server_def.command, pid,
                            )
                    except Exception:
                        logger.exception(
                            "MCPBridge reap raised for server '%s' pid=%d",
                            server_id, pid,
                        )

    async def stop_all(self) -> None:
        for server_id in list(self._servers):
            await self.stop_server(server_id)

    @property
    def server_ids(self) -> list[str]:
        return list(self._servers)


class _ServerConnection:
    __slots__ = ("server_id", "server_def", "session", "exit_stack", "tools", "pids")

    def __init__(
        self,
        server_id: str,
        server_def: MCPServerDef,
        session: ClientSession,
        exit_stack: AsyncExitStack,
        tools: list[dict[str, Any]],
        pids: frozenset[int] = frozenset(),
    ) -> None:
        self.server_id = server_id
        self.server_def = server_def
        self.session = session
        self.exit_stack = exit_stack
        self.tools = tools
        self.pids = pids


def _mcp_tool_to_openai(
    tool: Any, server_id: str
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
        "_mcp_server_id": server_id,
    }
