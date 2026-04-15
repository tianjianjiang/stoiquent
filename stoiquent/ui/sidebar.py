from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.models import Message

if TYPE_CHECKING:
    from stoiquent.persistence import ConversationStore

logger = logging.getLogger(__name__)

OnSessionSwitch = Callable[[str, list[Message]], None]


class Sidebar:
    """Tabbed sidebar with Sessions and Skills panels."""

    def __init__(
        self,
        session: Session,
        store: ConversationStore | None,
        on_session_switch: OnSessionSwitch,
    ) -> None:
        self._session = session
        self._store = store
        self._on_session_switch = on_session_switch
        self._sessions_container: ui.column | None = None

    async def render(self) -> None:
        with ui.tabs().classes("w-full") as tabs:
            sessions_tab = ui.tab("Sessions")
            ui.tab("Skills")

        with ui.tab_panels(tabs, value=sessions_tab).classes("w-full flex-grow"):
            with ui.tab_panel(sessions_tab):
                ui.button(
                    "New Chat", on_click=self._new_session
                ).classes("w-full").props("flat dense")
                ui.separator()
                self._sessions_container = ui.column().classes("w-full gap-1")
                await self._refresh_sessions()

            with ui.tab_panel("Skills"):
                self._render_skills_tab()

    async def _refresh_sessions(self) -> None:
        if self._sessions_container is None or self._store is None:
            return
        self._sessions_container.clear()
        try:
            summaries = await self._store.list_conversations_async()
        except Exception:
            logger.warning("Failed to load conversations", exc_info=True)
            with self._sessions_container:
                ui.label("Failed to load").classes("text-caption opacity-40")
            return

        with self._sessions_container:
            for summary in summaries:
                sid = summary.id
                ui.label(summary.title or sid).classes(
                    "text-caption cursor-pointer hover:bg-gray-100"
                ).on("click", lambda _, s=sid: self._load_session(s))

    async def _load_session(self, session_id: str) -> None:
        if self._store is None:
            return
        if self._session.messages:
            self._store.save_background(
                self._session.id, self._session.messages
            )
        record = await self._store.load_async(session_id)
        if record is None:
            ui.notify("Could not load conversation", type="warning")
            return
        self._on_session_switch(record.id, record.messages)
        await self._refresh_sessions()

    async def _new_session(self) -> None:
        if self._session.messages and self._store is not None:
            self._store.save_background(
                self._session.id, self._session.messages
            )
        new_id = uuid.uuid4().hex[:8]
        self._on_session_switch(new_id, [])
        await self._refresh_sessions()

    def _render_skills_tab(self) -> None:
        catalog = self._session.catalog
        if catalog is None:
            ui.label("No skills configured").classes("text-caption opacity-40")
            return

        if not catalog.skills:
            ui.label("No skills discovered").classes("text-caption opacity-40")
            return

        for name, skill in catalog.skills.items():
            with ui.row().classes("w-full items-center gap-2 py-1"):
                with ui.column().classes("flex-grow gap-0"):
                    ui.label(name).classes("text-sm font-medium")
                    ui.label(skill.meta.description).classes(
                        "text-xs opacity-60"
                    )
                ui.switch(
                    value=skill.active,
                    on_change=lambda e, n=name: self._toggle_skill(n, e.value),
                )

    def _toggle_skill(self, name: str, active: bool) -> None:
        catalog = self._session.catalog
        if catalog is None:
            return
        success = catalog.activate(name) if active else catalog.deactivate(name)
        if not success:
            action = "activate" if active else "deactivate"
            ui.notify(f"Failed to {action} skill '{name}'", type="warning")
