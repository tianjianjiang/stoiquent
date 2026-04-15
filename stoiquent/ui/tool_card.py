from __future__ import annotations

import json

from nicegui import ui

from stoiquent.models import ToolCall


def render_tool_call(tool_call: ToolCall) -> None:
    """Render a card showing tool name and arguments."""
    with ui.card().classes("w-full q-pa-sm"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("build").classes("text-blue-500")
            ui.label(tool_call.name).classes("font-mono text-sm font-bold")
        if tool_call.arguments:
            with ui.expansion("Arguments").classes("text-xs"):
                ui.code(
                    json.dumps(tool_call.arguments, indent=2), language="json"
                )


def render_tool_result(tool_call_id: str, content: str) -> None:
    """Render a card showing tool execution result."""
    with ui.card().classes("w-full q-pa-sm"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("check_circle").classes("text-green-500")
            ui.label("Result").classes("text-sm font-bold")
        if content:
            with ui.expansion("Output").classes("text-xs"):
                ui.code(content[:2000])
