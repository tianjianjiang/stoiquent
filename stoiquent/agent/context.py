from __future__ import annotations

from typing import Any

from stoiquent.agent.session import Session
from stoiquent.models import Message

BASE_SYSTEM_PROMPT = """\
You are Stoiquent, a helpful AI assistant running locally. \
You answer questions clearly and concisely. \
When reasoning through a problem, think step by step."""


def build_messages(
    session: Session,
) -> tuple[list[Message], list[dict[str, Any]] | None]:
    """Build the message list and tool schemas for an LLM call.

    Returns (messages, tools) where tools may be None if no skills are active.
    """
    system_parts = [BASE_SYSTEM_PROMPT]

    if session.catalog:
        catalog_prompt = session.catalog.get_catalog_prompt()
        if catalog_prompt:
            system_parts.append(catalog_prompt)

        instructions = session.catalog.get_active_instructions()
        if instructions:
            system_parts.append(instructions)

    system_content = "\n\n".join(system_parts)
    system_msg = Message(role="system", content=system_content)

    tools: list[dict[str, Any]] | None = None
    if session.catalog:
        active_tools = session.catalog.get_active_tools()
        if active_tools:
            tools = active_tools

    return [system_msg, *session.messages], tools
