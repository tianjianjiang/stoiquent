from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from stoiquent.skills.controller import SkillController
    from stoiquent.skills.models import Skill

logger = logging.getLogger(__name__)


DiscoverCallable = Callable[[], "dict[str, Skill]"]

_SOURCE_ORDER: tuple[str, ...] = ("user", "project", "config")
_ALL_LABEL = "All"


class SkillsManager:
    """Full-width overlay dialog for managing skills.

    Renders a maximized ``ui.dialog`` with search, source filter, reload,
    and per-skill rows grouped by source. All mutations route through the
    injected :class:`SkillController`; UI is a pure view that re-renders
    via ``controller.subscribe``.

    Construct once per page render. ``build()`` must be called inside a
    NiceGUI page context before ``open()`` is reachable.
    """

    def __init__(
        self,
        controller: SkillController | None,
        *,
        discover: DiscoverCallable | None = None,
    ) -> None:
        self._controller = controller
        self._discover = discover
        self._dialog: ui.dialog | None = None
        self._body_container: ui.column | None = None
        self._search: ui.input | None = None
        self._source_filter: ui.select | None = None
        self._unsubscribe: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        return self._controller is not None

    def build(self) -> None:
        """Create the dialog widget tree. No-op when no controller is available."""
        if self._controller is None:
            return
        with ui.dialog().props("maximized") as dialog:
            dialog.mark("skills-manager-dialog")
            with ui.card().classes("w-full h-full column no-wrap"):
                self._build_header(dialog)
                self._body_container = (
                    ui.column()
                    .classes("w-full flex-grow overflow-auto gap-3 p-4")
                    .mark("skills-manager-body")
                )
                self._refresh()
        self._dialog = dialog
        self._unsubscribe = self._controller.subscribe(self._refresh)

    def open(self) -> None:
        if self._dialog is not None:
            self._dialog.open()

    def teardown(self) -> None:
        """Unsubscribe from controller updates. Call when disposing the page."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _build_header(self, dialog: ui.dialog) -> None:
        with ui.row().classes(
            "w-full items-center gap-3 p-3 border-b border-neutral-800"
        ):
            ui.label("Skills").classes("text-h6")
            ui.space()
            search = (
                ui.input(placeholder="Search skills…")
                .props("dense clearable")
                .classes("w-60")
                .mark("skills-manager-search")
            )
            search.on("update:model-value", lambda _: self._refresh())
            self._search = search
            self._source_filter = (
                ui.select(
                    [_ALL_LABEL, "User", "Project", "Config"],
                    value=_ALL_LABEL,
                    on_change=lambda _: self._refresh(),
                )
                .props("dense")
                .mark("skills-manager-source")
            )
            ui.button(
                "Reload", icon="refresh", on_click=self._on_reload
            ).props("flat dense").mark("skills-manager-reload")
            ui.button("Close", on_click=dialog.close).props("flat dense").mark(
                "skills-manager-close"
            )

    def _refresh(self) -> None:
        if self._body_container is None or self._controller is None:
            return
        self._body_container.clear()
        visible = self._filtered_skills()
        with self._body_container:
            if not visible:
                ui.label(
                    "No skills match — drop a SKILL.md into "
                    "~/.stoiquent/skills/<name>/ and click Reload."
                ).classes("text-caption opacity-60")
                return
            groups = _group_by_source(visible)
            for source in _SOURCE_ORDER:
                items = groups.get(source, [])
                if not items:
                    continue
                with ui.expansion(
                    f"{source.title()} ({len(items)})", value=True
                ).classes("w-full").mark(f"skills-manager-group-{source}"):
                    for skill in items:
                        self._render_row(skill)

    def _filtered_skills(self) -> list[Skill]:
        assert self._controller is not None
        query = (self._search.value if self._search else "") or ""
        query = query.strip().lower()
        selected = (
            self._source_filter.value if self._source_filter else _ALL_LABEL
        ) or _ALL_LABEL
        source_filter = None if selected == _ALL_LABEL else selected.lower()
        out: list[Skill] = []
        for skill in self._controller.catalog.skills.values():
            if source_filter is not None and skill.source != source_filter:
                continue
            if query and not _matches_query(skill, query):
                continue
            out.append(skill)
        out.sort(key=lambda s: s.meta.name)
        return out

    def _render_row(self, skill: Skill) -> None:
        name = skill.meta.name
        with ui.row().classes(
            "w-full items-center gap-3 py-2 border-b border-neutral-900"
        ).mark(f"skill-row-{name}"):
            ui.switch(
                value=skill.active,
                on_change=lambda e, n=name: self._on_toggle(n, bool(e.value)),
            ).mark(f"skill-switch-{name}")
            with ui.column().classes("flex-grow gap-0"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(name).classes("text-sm font-medium")
                    if skill.meta.version:
                        ui.label(f"v{skill.meta.version}").classes(
                            "text-xs opacity-60"
                        )
                    for tag in skill.meta.tags:
                        ui.badge(f"#{tag}").props("color=grey-7 outline")
                    if skill.meta.mcp_servers:
                        ui.badge(
                            f"MCP · {len(skill.meta.mcp_servers)}"
                        ).props("color=blue outline")
                if skill.meta.description:
                    ui.label(skill.meta.description).classes(
                        "text-xs opacity-60"
                    )
            ui.button(
                "View SKILL.md",
                on_click=lambda _, s=skill: self._open_view_dialog(s),
            ).props("flat dense").mark(f"skill-view-{name}")

    async def _on_toggle(self, name: str, active: bool) -> None:
        if self._controller is None:
            return
        result = (
            await self._controller.activate(name)
            if active
            else await self._controller.deactivate(name)
        )
        if not result.success:
            verb = "activate" if active else "deactivate"
            ui.notify(
                f"Failed to {verb} '{name}': {result.reason}", type="warning"
            )

    async def _on_reload(self) -> None:
        if self._controller is None:
            return
        if self._discover is None:
            ui.notify(
                "Reload unavailable — no discover callable configured",
                type="warning",
            )
            return
        result = await self._controller.reload_from_disk(self._discover)
        summary_parts: list[str] = []
        if result.added:
            summary_parts.append(f"+{len(result.added)} added")
        if result.removed:
            summary_parts.append(f"−{len(result.removed)} removed")
        if not summary_parts:
            summary_parts.append("no changes")
        ui.notify("Reload: " + ", ".join(summary_parts))
        if result.deactivation_failures:
            ui.notify(
                "MCP cleanup failed for: "
                + ", ".join(result.deactivation_failures),
                type="warning",
            )

    def _open_view_dialog(self, skill: Skill) -> None:
        with ui.dialog().props("maximized") as view, ui.card().classes(
            "w-full h-full column no-wrap"
        ):
            view.mark(f"skill-view-dialog-{skill.meta.name}")
            with ui.row().classes(
                "w-full items-center gap-3 p-3 border-b border-neutral-800"
            ):
                ui.label(skill.meta.name).classes("text-h6")
                if skill.meta.version:
                    ui.label(f"v{skill.meta.version}").classes(
                        "text-caption opacity-60"
                    )
                ui.space()
                ui.button("Close", on_click=view.close).props("flat dense")
            with ui.scroll_area().classes("w-full flex-grow p-4"):
                ui.label(str(skill.path)).classes("text-caption opacity-60")
                ui.separator()
                ui.markdown(skill.instructions or "*(no instructions)*")
        view.open()


def _matches_query(skill: Skill, query: str) -> bool:
    haystacks = (
        skill.meta.name.lower(),
        skill.meta.description.lower(),
        *(t.lower() for t in skill.meta.tags),
    )
    return any(query in h for h in haystacks)


def _group_by_source(skills: list[Skill]) -> dict[str, list[Skill]]:
    groups: dict[str, list[Skill]] = {}
    for skill in skills:
        groups.setdefault(skill.source, []).append(skill)
    return groups
