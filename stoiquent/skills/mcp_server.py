from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from stoiquent.models import AppConfig
from stoiquent.sandbox.detect import detect_backend
from stoiquent.sandbox.models import SandboxPolicy
from stoiquent.sandbox.policy import default_policy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.discovery import discover_skills
from stoiquent.skills.executor import build_command, resolve_script

logger = logging.getLogger(__name__)


def create_mcp_server(
    config: AppConfig,
    skills_dir: str | None = None,
) -> FastMCP:
    """Create an MCP server exposing active skills as tools.

    Discovers skills, activates all of them, and registers each skill's
    tools as MCP tools that delegate to the sandbox executor.
    """
    mcp = FastMCP("Stoiquent Skills Server")

    catalog = SkillCatalog(discover_skills(config.skills))
    sandbox = detect_backend(config.sandbox)
    policy = default_policy()
    timeout = config.sandbox.tool_timeout

    for name in list(catalog.skills):
        try:
            catalog.activate(name)
        except Exception:
            logger.error("Failed to activate skill '%s', skipping", name, exc_info=True)

    for skill in catalog.get_active_skills():
        for tool_def in skill.meta.tools:
            _register_tool(mcp, tool_def.name, tool_def.description, skill, sandbox, policy, timeout)

    logger.info(
        "MCP server created with %d tools from %d skills",
        len(catalog.get_active_tools()),
        len(catalog.get_active_skills()),
    )
    return mcp


def _register_tool(
    mcp: FastMCP,
    tool_name: str,
    tool_description: str,
    skill: Any,
    sandbox: Any,
    policy: SandboxPolicy,
    timeout: float,
) -> None:
    import json

    async def _handler(**kwargs: Any) -> str:
        script = resolve_script(skill.path, tool_name)
        if script is None:
            return f"Error: No script found for tool '{tool_name}'"

        command = build_command(script)
        if kwargs:
            command.append(json.dumps(kwargs))

        result = await sandbox.execute(
            command=command,
            policy=policy,
            workdir=str(skill.path),
            timeout=timeout,
        )

        if result.timed_out:
            return f"Error: Tool '{tool_name}' timed out"

        if result.exit_code != 0:
            output = (result.stderr or "").strip() or (result.stdout or "").strip()
            return f"Error (exit {result.exit_code}): {output}" if output else (
                f"Error: Tool '{tool_name}' failed with exit code {result.exit_code}"
            )

        return result.stdout or ""

    _handler.__name__ = tool_name
    _handler.__doc__ = tool_description or f"Execute {tool_name}"

    mcp.tool()(_handler)
