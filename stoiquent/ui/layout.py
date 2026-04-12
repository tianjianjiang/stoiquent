from __future__ import annotations

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.ui.chat import ChatPanel


def render(session: Session) -> None:
    with ui.header().classes("items-center gap-4 px-4"):
        ui.label("Stoiquent").classes("text-h6 font-bold")
        ui.space()
        ui.label("Local LLM Agent").classes("text-caption opacity-60")

    with ui.splitter(value=20).classes("w-full h-screen") as splitter:
        with splitter.before:
            with ui.column().classes("w-full p-2 gap-2"):
                ui.label("Sessions").classes("text-subtitle2 opacity-60")
                ui.separator()
                ui.label("Coming in Phase 5").classes("text-caption opacity-40")

        with splitter.after:
            chat = ChatPanel(session)
            chat.render()
