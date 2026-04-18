from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import ui
from pydantic import ValidationError

from stoiquent.agent.session import Session
from stoiquent.models import Message
from stoiquent.projects import ProjectRecord

if TYPE_CHECKING:
    from stoiquent.persistence import ConversationStore, ConversationSummary
    from stoiquent.projects import ProjectStore, ProjectSummary

logger = logging.getLogger(__name__)

OnSessionSwitch = Callable[[str, list[Message], str | None], None]

_UNGROUPED_LABEL = "Ungrouped"


class Sidebar:
    """Tabbed sidebar with Sessions, Projects, and Skills panels."""

    def __init__(
        self,
        session: Session,
        store: ConversationStore | None,
        on_session_switch: OnSessionSwitch,
        project_store: ProjectStore | None = None,
    ) -> None:
        self._session = session
        self._store = store
        self._project_store = project_store
        self._on_session_switch = on_session_switch
        self._sessions_container: ui.column | None = None
        self._projects_container: ui.column | None = None
        self._active_project_id: str | None = None

    async def render(self) -> None:
        with ui.tabs().classes("w-full").mark("sidebar-tabs") as tabs:
            sessions_tab = ui.tab("Sessions").mark("sessions-tab")
            ui.tab("Projects").mark("projects-tab")
            ui.tab("Skills").mark("skills-tab")

        with ui.tab_panels(tabs, value=sessions_tab).classes("w-full flex-grow"):
            with ui.tab_panel(sessions_tab):
                ui.button(
                    "New Chat", on_click=self._new_session
                ).classes("w-full").props("flat dense").mark("new-chat-btn")
                ui.separator()
                self._sessions_container = (
                    ui.column().classes("w-full gap-1").mark("sessions-list")
                )
                await self._refresh_sessions()

            with ui.tab_panel("Projects"):
                ui.button(
                    "+ New Project", on_click=self._open_new_project_dialog
                ).classes("w-full").props("flat dense").mark("new-project-btn")
                ui.separator()
                self._projects_container = (
                    ui.column().classes("w-full gap-1").mark("projects-list")
                )
                await self._refresh_projects()

            with ui.tab_panel("Skills"):
                self._render_skills_tab()

    # --- Sessions tab ---

    async def _refresh_sessions(self) -> None:
        if self._sessions_container is None or self._store is None:
            return
        self._sessions_container.clear()
        try:
            summaries = await self._store.list_conversations_async()
        except (OSError, json.JSONDecodeError, ValidationError):
            logger.warning("Failed to load conversations", exc_info=True)
            with self._sessions_container:
                ui.label("Failed to load").classes("text-caption opacity-40")
            ui.notify("Could not load conversation list", type="warning")
            return

        projects = await self._list_projects_safe()
        grouped: dict[str | None, list[ConversationSummary]] = {}
        for summary in summaries:
            grouped.setdefault(summary.project_id, []).append(summary)

        with self._sessions_container:
            for project in projects:
                convs = grouped.pop(project.id, [])
                if convs:
                    self._render_session_group(project.name, convs)
            # Everything left has project_id=None, points at a project
            # that no longer exists, or belongs to a project the store
            # failed to load; all three render under Ungrouped.
            leftover = [s for bucket in grouped.values() for s in bucket]
            if leftover:
                self._render_session_group(_UNGROUPED_LABEL, leftover)

    def _render_session_group(
        self, label: str, conversations: list[ConversationSummary]
    ) -> None:
        ui.label(label).classes("text-caption opacity-60 font-medium mt-2")
        for summary in conversations:
            sid = summary.id

            async def on_click(_: object, s: str = sid) -> None:
                await self._load_session(s)

            ui.label(summary.title or sid).classes(
                "text-caption cursor-pointer hover:bg-gray-100 pl-2"
            ).on("click", on_click)

    async def _load_session(self, session_id: str) -> None:
        if self._store is None:
            return
        if self._session.messages:
            self._store.save_background(
                self._session.id,
                self._session.messages,
                self._session.project_id,
            )
        try:
            record = await self._store.load_async(session_id)
        except (OSError, json.JSONDecodeError, ValidationError):
            logger.warning("Failed to load conversation: %s", session_id, exc_info=True)
            ui.notify("Could not load conversation", type="warning")
            return
        if record is None:
            ui.notify("Could not load conversation", type="warning")
            return
        self._on_session_switch(record.id, record.messages, record.project_id)
        await self._refresh_sessions()

    async def _new_session(self) -> None:
        if self._session.messages and self._store is not None:
            self._store.save_background(
                self._session.id,
                self._session.messages,
                self._session.project_id,
            )
        new_id = uuid.uuid4().hex[:8]
        self._on_session_switch(new_id, [], self._active_project_id)
        await self._refresh_sessions()

    # --- Projects tab ---

    async def _list_projects_safe(self) -> list[ProjectSummary]:
        """Return the current project list, or ``[]`` if loading fails.

        Failures here collapse projects-tab rendering AND session grouping
        (every project-tagged conversation is rendered under "Ungrouped"
        until the next successful load). Logged at ERROR; there is no
        dedicated UI banner today, so operators need to watch logs to
        tell "empty" from "failed".
        """
        if self._project_store is None:
            return []
        try:
            return await self._project_store.list_projects_async()
        except (OSError, json.JSONDecodeError, ValidationError):
            logger.error("Failed to load projects", exc_info=True)
            return []

    async def _refresh_projects(self) -> None:
        if self._projects_container is None:
            return
        self._projects_container.clear()

        if self._project_store is None:
            with self._projects_container:
                ui.label("No project store configured").classes(
                    "text-caption opacity-40"
                )
            return

        projects = await self._list_projects_safe()
        with self._projects_container:
            if not projects:
                ui.label("No projects yet").classes("text-caption opacity-40")
                return
            for project in projects:
                self._render_project_row(project)

    def _render_project_row(self, project: ProjectSummary) -> None:
        is_active = project.id == self._active_project_id
        classes = "w-full items-center gap-2 py-1 cursor-pointer"
        if is_active:
            classes += " bg-blue-50"
        with ui.row().classes(classes):
            label = ui.label(project.name).classes("text-sm flex-grow")

            async def on_click_activate(_e: object, pid: str = project.id) -> None:
                await self._set_active_project(pid)

            label.on("click", on_click_activate)
            ui.button(
                icon="edit",
                on_click=lambda _e, pid=project.id: self._open_edit_project_dialog(pid),
            ).props("flat dense round size=sm").mark(f"edit-project-{project.id}")
            ui.button(
                icon="delete",
                on_click=lambda _e, pid=project.id: self._open_delete_project_dialog(
                    pid
                ),
            ).props("flat dense round size=sm color=negative").mark(
                f"delete-project-{project.id}"
            )

    async def _set_active_project(self, project_id: str | None) -> None:
        """Flip the active project and re-render so the highlight paints.

        NiceGUI does not bind ``self._active_project_id`` to the already
        rendered row's ``classes``; without a refresh the ``bg-blue-50``
        class never appears and the click feels broken.
        """
        self._active_project_id = project_id
        await self._refresh_projects()

    def _open_new_project_dialog(self) -> None:
        if self._project_store is None:
            return
        with ui.dialog() as dialog, ui.card().classes("min-w-80"):
            ui.label("New Project").classes("text-h6")
            name_input = ui.input("Name").classes("w-full").mark("new-project-name")
            folder_input = ui.input("Folder").classes("w-full").mark(
                "new-project-folder"
            )
            instructions_input = (
                ui.textarea("Instructions")
                .classes("w-full")
                .props("rows=4")
                .mark("new-project-instructions")
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def _save() -> None:
                    await self._create_project(
                        name_input.value or "",
                        folder_input.value or "",
                        instructions_input.value or "",
                    )
                    dialog.close()

                ui.button("Create", on_click=_save).mark("new-project-save")
        dialog.open()

    async def _create_project(
        self, name: str, folder: str, instructions: str
    ) -> None:
        if self._project_store is None:
            return
        name = name.strip()
        folder = folder.strip()
        if not name or not folder:
            ui.notify("Name and folder are required", type="warning")
            return
        project_id = uuid.uuid4().hex[:8]
        record = ProjectRecord(
            id=project_id, name=name, folder=folder, instructions=instructions
        )
        try:
            await self._project_store.save(record)
        except OSError:
            logger.error("Failed to save project %s", project_id, exc_info=True)
            ui.notify("Failed to create project", type="warning")
            return
        await self._refresh_projects()

    def _open_edit_project_dialog(self, project_id: str) -> None:
        if self._project_store is None:
            return
        record = self._project_store.load(project_id)
        if record is None:
            ui.notify("Project not found", type="warning")
            return
        with ui.dialog() as dialog, ui.card().classes("min-w-80"):
            ui.label("Edit Project").classes("text-h6")
            name_input = ui.input("Name", value=record.name).classes("w-full")
            folder_input = ui.input("Folder", value=record.folder).classes("w-full")
            instructions_input = (
                ui.textarea("Instructions", value=record.instructions)
                .classes("w-full")
                .props("rows=4")
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def _save() -> None:
                    await self._update_project(
                        record,
                        name_input.value or "",
                        folder_input.value or "",
                        instructions_input.value or "",
                    )
                    dialog.close()

                ui.button("Save", on_click=_save).mark(f"save-project-{project_id}")
        dialog.open()

    async def _update_project(
        self,
        record: ProjectRecord,
        name: str,
        folder: str,
        instructions: str,
    ) -> None:
        if self._project_store is None:
            return
        name = name.strip()
        folder = folder.strip()
        if not name or not folder:
            ui.notify("Name and folder are required", type="warning")
            return
        updated = record.model_copy(
            update={"name": name, "folder": folder, "instructions": instructions}
        )
        try:
            await self._project_store.save(updated)
        except OSError:
            logger.error("Failed to update project %s", record.id, exc_info=True)
            ui.notify("Failed to update project", type="warning")
            return
        # If the active session belongs to this project, refresh its instructions
        # so the next agent turn sees the new prompt immediately.
        if self._session.project_id == record.id:
            self._session.project_instructions = updated.instructions
        await self._refresh_projects()
        await self._refresh_sessions()

    def _open_delete_project_dialog(self, project_id: str) -> None:
        if self._project_store is None:
            return
        record = self._project_store.load(project_id)
        if record is None:
            ui.notify("Project not found", type="warning")
            return
        affected = self._count_conversations_for_project(project_id)
        with ui.dialog() as dialog, ui.card().classes("min-w-80"):
            ui.label(f"Delete '{record.name}'?").classes("text-h6")
            if affected is None:
                ui.label(
                    "Could not determine how many conversations will be "
                    "deleted (read failure — check logs)."
                ).classes("text-caption")
            else:
                suffix = "conversation" if affected == 1 else "conversations"
                ui.label(
                    f"This will also delete {affected} {suffix}."
                ).classes("text-caption")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def _confirm() -> None:
                    await self._delete_project(project_id)
                    dialog.close()

                ui.button("Delete", on_click=_confirm).props("color=negative").mark(
                    f"confirm-delete-{project_id}"
                )
        dialog.open()

    def _count_conversations_for_project(self, project_id: str) -> int | None:
        """Count conversations for a project, or ``None`` on read failure.

        The return feeds a destructive-action confirmation dialog; returning
        ``0`` on failure would let users approve a delete they believe is a
        no-op. ``None`` tells the dialog to render a "count unavailable"
        message so the user can make an informed choice.
        """
        if self._store is None:
            return 0
        try:
            return len(self._store.list_conversations(project_id))
        except (OSError, json.JSONDecodeError, ValidationError):
            logger.error(
                "Failed to count conversations for project %s",
                project_id,
                exc_info=True,
            )
            return None

    async def _delete_project(self, project_id: str) -> None:
        """Cascade-delete a project and its conversations.

        Order: conversations first, project record second. The user's
        explicit requirement for this PR is "no orphan sessions" — so the
        project-record delete is gated on ``result.complete``, which is
        True only when ``unlink_failed``, ``skipped_unparseable``, and
        ``skipped_unreadable`` are all zero. Otherwise the project record
        survives and the cascade can be retried; orphaned conversations
        would violate the invariant.
        """
        if self._project_store is None:
            return
        if self._store is not None:
            try:
                result = await self._store.delete_by_project_async(project_id)
            except OSError:
                logger.error(
                    "Failed to cascade-delete conversations for project %s",
                    project_id,
                    exc_info=True,
                )
                ui.notify("Failed to delete project conversations", type="warning")
                return
            if not result.complete:
                # Report every failure category so the user can tell
                # whether a retry might succeed (unlink failures can be
                # transient) or whether the blocker is structural and
                # needs manual file repair (unparseable / unreadable).
                # On this branch at least one of the three failure
                # counters (unlink_failed, skipped_unparseable,
                # skipped_unreadable) is > 0 by definition, so the
                # retriable test reduces to "no structural blocker".
                retriable = (
                    result.skipped_unparseable == 0
                    and result.skipped_unreadable == 0
                )
                guidance = (
                    "retry after the transient error clears"
                    if retriable
                    else "repair or remove the offending files before retrying"
                )
                ui.notify(
                    f"Cascade incomplete — deleted {result.deleted}, "
                    f"unlink_failed={result.unlink_failed}, "
                    f"unparseable={result.skipped_unparseable}, "
                    f"unreadable={result.skipped_unreadable}. "
                    f"Project kept so you can {guidance}. Check logs.",
                    type="warning",
                )
                await self._refresh_projects()
                await self._refresh_sessions()
                return
        if not self._project_store.delete(project_id):
            ui.notify("Failed to delete project", type="warning")
            await self._refresh_projects()
            await self._refresh_sessions()
            return
        if self._active_project_id == project_id:
            self._active_project_id = None
        if self._session.project_id == project_id:
            self._session.project_id = None
            self._session.project_instructions = ""
        await self._refresh_projects()
        await self._refresh_sessions()

    # --- Skills tab ---

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
