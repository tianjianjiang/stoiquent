from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from stoiquent.skills.controller import SkillController
    from stoiquent.ui.skills_manager import SkillsManager

logger = logging.getLogger(__name__)


class SkillsHeaderMenu:
    """Header button + dropdown for quick skill activation.

    Mirrors AnythingLLM's chat-bar "Tools" toggle
    (https://docs.anythingllm.com/agent/custom/introduction): a compact
    glance at active/total plus a per-skill switch surface that doesn't
    require opening the manager. Clicking the "Manage skills…" footer
    opens the shared :class:`SkillsManager` overlay.

    Construct and call :meth:`build` from inside the header row of
    ``layout.render``. The button is hidden entirely when the catalog is
    empty so the header stays uncluttered on fresh installs.
    """

    def __init__(
        self,
        controller: SkillController | None,
        *,
        manager: SkillsManager | None = None,
    ) -> None:
        self._controller = controller
        self._manager = manager
        self._button: ui.button | None = None
        self._menu: ui.menu | None = None
        self._body_container: ui.column | None = None
        self._unsubscribe: Callable[[], None] | None = None

    def build(self) -> None:
        if self._controller is None:
            return
        skills = self._controller.catalog.skills
        if not skills:
            return
        button = (
            ui.button(self._label_text())
            .props("flat dense")
            .classes("text-caption")
            .mark("skills-header-button")
        )
        with button:
            menu = ui.menu().props("anchor='bottom right' self='top right'")
            with menu:
                body = (
                    ui.column()
                    .classes("gap-0 p-2 min-w-56")
                    .mark("skills-header-body")
                )
        self._button = button
        self._menu = menu
        self._body_container = body
        self._refresh()
        self._unsubscribe = self._controller.subscribe(self._refresh)

    def teardown(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _label_text(self) -> str:
        assert self._controller is not None
        total = len(self._controller.catalog.skills)
        active = len(self._controller.active_names())
        return f"Skills · {active}/{total}"

    def _refresh(self) -> None:
        if self._button is None or self._body_container is None:
            return
        if self._controller is None:
            return
        self._button.set_text(self._label_text())
        self._body_container.clear()
        with self._body_container:
            skills = sorted(
                self._controller.catalog.skills.values(),
                key=lambda s: s.meta.name,
            )
            for skill in skills:
                self._render_row(skill)
            ui.separator()
            manage_btn = (
                ui.button("Manage skills…", on_click=self._open_manager)
                .classes("w-full")
                .props("flat dense")
                .mark("skills-header-manage-btn")
            )
            if self._manager is None or not self._manager.available:
                manage_btn.disable()

    def _render_row(self, skill: object) -> None:
        name = skill.meta.name  # type: ignore[attr-defined]
        description = skill.meta.description  # type: ignore[attr-defined]
        active = skill.active  # type: ignore[attr-defined]
        with ui.row().classes("w-full items-center gap-2 py-1").mark(
            f"skills-header-row-{name}"
        ):
            ui.switch(
                value=active,
                on_change=lambda e, n=name: self._on_toggle(n, bool(e.value)),
            ).mark(f"skills-header-switch-{name}")
            with ui.column().classes("flex-grow gap-0"):
                ui.label(name).classes("text-sm font-medium")
                if description:
                    ui.label(description).classes("text-xs opacity-60")

    async def _on_toggle(self, name: str, active: bool) -> None:
        if self._controller is None:
            return
        result = (
            await self._controller.activate(name)
            if active
            else await self._controller.deactivate(name)
        )
        for warning in result.warnings:
            ui.notify(warning, type="warning")
        if not result.success:
            verb = "activate" if active else "deactivate"
            ui.notify(
                f"Failed to {verb} '{name}': {result.reason}", type="warning"
            )

    def _open_manager(self) -> None:
        if self._manager is not None:
            self._manager.open()
