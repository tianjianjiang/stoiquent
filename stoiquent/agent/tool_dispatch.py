from __future__ import annotations

import asyncio
import json
import logging

from stoiquent.models import ToolCall
from stoiquent.sandbox.base import SandboxBackend
from stoiquent.sandbox.models import SandboxPolicy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.executor import build_command, resolve_script
from stoiquent.skills.mcp_bridge import MCPBridge
from stoiquent.skills.models import Skill, SkillToolDef

logger = logging.getLogger(__name__)


async def dispatch_tool_call(
    tool_call: ToolCall,
    catalog: SkillCatalog,
    sandbox: SandboxBackend,
    policy: SandboxPolicy,
    timeout: float,
    mcp_bridge: MCPBridge | None = None,
) -> str:
    """Route a tool call to the appropriate skill executor or MCP server.

    Returns the tool result as a string. Never raises -- errors are
    returned as descriptive strings so the LLM can see them.
    """
    try:
        if mcp_bridge is not None:
            server_id = mcp_bridge.find_server_for_tool(tool_call.name)
            if server_id is not None:
                logger.info("Routing tool '%s' to MCP server '%s'", tool_call.name, server_id)
                try:
                    return await asyncio.wait_for(
                        mcp_bridge.call_tool(
                            server_id, tool_call.name, tool_call.arguments,
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    return f"Error: MCP tool '{tool_call.name}' timed out after {timeout}s"
        return await _execute_tool(tool_call, catalog, sandbox, policy, timeout)
    except Exception as e:
        logger.exception("Unexpected error dispatching tool '%s'", tool_call.name)
        return f"Error: Unexpected failure in '{tool_call.name}': {e}"


async def _execute_tool(
    tool_call: ToolCall,
    catalog: SkillCatalog,
    sandbox: SandboxBackend,
    policy: SandboxPolicy,
    timeout: float,
) -> str:
    skill, tool_def = _find_tool(catalog, tool_call.name)
    if skill is None or tool_def is None:
        return f"Error: Unknown tool '{tool_call.name}'"

    script = resolve_script(skill.path, tool_call.name)
    if script is None:
        return f"Error: No script found for tool '{tool_call.name}' in {skill.path}/scripts/"

    command = build_command(script)
    if tool_call.arguments:
        command.append(json.dumps(tool_call.arguments))

    logger.info("Executing tool '%s' via %s", tool_call.name, sandbox.name())

    result = await sandbox.execute(
        command=command,
        policy=policy,
        workdir=str(skill.path),
        timeout=timeout,
    )

    if result.timed_out:
        return f"Error: Tool '{tool_call.name}' timed out after {timeout}s"

    if result.exit_code != 0:
        output = (result.stderr or "").strip() or (result.stdout or "").strip()
        return f"Error (exit {result.exit_code}): {output}" if output else (
            f"Error: Tool '{tool_call.name}' failed with exit code {result.exit_code}"
        )

    return result.stdout or ""


def _find_tool(
    catalog: SkillCatalog, tool_name: str
) -> tuple[Skill | None, SkillToolDef | None]:
    for skill in catalog.get_active_skills():
        for tool_def in skill.meta.tools:
            if tool_def.name == tool_name:
                return skill, tool_def
    return None, None
