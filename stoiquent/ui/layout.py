from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.ui.chat import ChatPanel

if TYPE_CHECKING:
    from stoiquent.persistence import ConversationStore

logger = logging.getLogger(__name__)


async def render(session: Session, store: ConversationStore | None = None) -> None:
    with ui.header().classes("items-center gap-4 px-4"):
        ui.label("Stoiquent").classes("text-h6 font-bold")
        ui.space()
        ui.label("Local LLM Agent").classes("text-caption opacity-60")

    with ui.splitter(value=20).classes("w-full h-screen") as splitter:
        with splitter.before:
            with ui.column().classes("w-full p-2 gap-2"):
                ui.label("Sessions").classes("text-subtitle2 opacity-60")
                ui.separator()
                if store is not None:
                    try:
                        for summary in await store.list_conversations_async():
                            ui.label(summary.title or summary.id).classes(
                                "text-caption cursor-pointer"
                            )
                    except Exception:
                        logger.warning(
                            "Failed to load conversation list", exc_info=True
                        )
                        ui.label("Failed to load conversations").classes(
                            "text-caption opacity-40"
                        )
                else:
                    ui.label("No persistence configured").classes(
                        "text-caption opacity-40"
                    )

        with splitter.after:
            chat = ChatPanel(session, store)
            chat.render()
