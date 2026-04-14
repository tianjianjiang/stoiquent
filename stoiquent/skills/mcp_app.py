from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from stoiquent.skills.models import MCPAppDef, Skill

logger = logging.getLogger(__name__)


def get_app_resource_uri(skill: Skill) -> str | None:
    """Return the ui:// resource URI for a skill's MCP app, or None."""
    if skill.meta.mcp_app is None:
        return None
    return f"ui://{skill.meta.name}/{skill.meta.mcp_app.resource}"


def resolve_app_html(skill: Skill) -> Path | None:
    """Resolve the HTML file path for a skill's MCP app."""
    if skill.meta.mcp_app is None:
        return None
    html_path = skill.path / skill.meta.mcp_app.resource
    if html_path.is_file():
        return html_path
    logger.warning(
        "MCP app resource '%s' not found at %s",
        skill.meta.mcp_app.resource,
        html_path,
    )
    return None


def get_app_metadata(skill: Skill) -> dict[str, Any] | None:
    """Return MCP app metadata for tool descriptions, or None."""
    if skill.meta.mcp_app is None:
        return None
    uri = get_app_resource_uri(skill)
    return {
        "ui": {
            "resourceUri": uri,
            "mimeType": "text/html;profile=mcp-app",
            "permissions": skill.meta.mcp_app.permissions,
            "csp": skill.meta.mcp_app.csp,
        }
    }


def inject_app_meta_into_tools(
    tools: list[dict[str, Any]], skill: Skill
) -> list[dict[str, Any]]:
    """Add _meta.ui.resourceUri to tool descriptions for skills with MCP apps."""
    meta = get_app_metadata(skill)
    if meta is None:
        return tools
    return [
        {**tool, "_meta": meta}
        for tool in tools
    ]
