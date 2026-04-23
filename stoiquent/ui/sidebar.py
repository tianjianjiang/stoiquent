from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nicegui import ui
from pydantic import ValidationError

from stoiquent.agent.session import Session
from stoiquent.models import Message
from stoiquent.projects import ProjectDeleteResult, ProjectLoadError, ProjectRecord

if TYPE_CHECKING:
    from stoiquent.persistence import ConversationStore, ConversationSummary
    from stoiquent.projects import ProjectStore, ProjectSummary
    from stoiquent.ui.skills_manager import SkillsManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionSwitch:
    """Intent to move the active chat to a new session.

    Bundles the three fields ``_apply_session_switch`` needs so they can be
    resolved atomically: ``_load_project_instructions`` runs before any
    mutation, and if it ever raises the session stays untouched. The frozen
    bundle also keeps dispatch state from being mutated mid-apply.

    ``messages`` is stored by reference on purpose — callers hand over
    fresh lists (`[]` on new chat, `record.messages` on load, or the
    session's own list on project detach/update routing) and the receiver
    rebinds `session.messages`. If a snapshot is ever needed, copy at the
    call site; do not add a defensive copy here (would cost a list copy
    per switch for no current caller).
    """

    session_id: str
    messages: list[Message]
    project_id: str | None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("SessionSwitch.session_id must be non-empty")


OnSessionSwitch = Callable[[SessionSwitch], None]

_UNGROUPED_LABEL = "— Ungrouped"
"""Session-group header for conversations with no project or a deleted/missing one.

Prefixed with an em-dash so a user who literally names a project "Ungrouped"
renders as a distinct group from this bucket. Without the prefix the two
groups share a header and read as a single list.
"""


class Sidebar:
    """Tabbed sidebar with Sessions, Projects, and Skills panels."""

    def __init__(
        self,
        session: Session,
        store: ConversationStore | None,
        on_session_switch: OnSessionSwitch,
        project_store: ProjectStore,
        *,
        skills_manager: SkillsManager | None = None,
    ) -> None:
        self._session = session
        self._store = store
        self._project_store = project_store
        self._on_session_switch = on_session_switch
        self._skills_manager = skills_manager
        self._sessions_container: ui.column | None = None
        self._projects_container: ui.column | None = None
        self._skills_container: ui.column | None = None
        self._skills_unsubscribe: Callable[[], None] | None = None
        self._active_project_id: str | None = None
        # Optimistic baseline: a fresh sidebar has no known failure.
        # Flips to False on the first _list_projects_safe failure so a
        # recovery toast can be suppressed until the next transition.
        self._projects_load_healthy: bool = True

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
        self._on_session_switch(
            SessionSwitch(
                session_id=record.id,
                messages=record.messages,
                project_id=record.project_id,
            )
        )
        await self._refresh_sessions()

    async def _new_session(self) -> None:
        if self._session.messages and self._store is not None:
            self._store.save_background(
                self._session.id,
                self._session.messages,
                self._session.project_id,
            )
        new_id = uuid.uuid4().hex[:8]
        self._on_session_switch(
            SessionSwitch(
                session_id=new_id,
                messages=[],
                project_id=self._active_project_id,
            )
        )
        await self._refresh_sessions()

    # --- Projects tab ---

    async def _list_projects_safe(self) -> list[ProjectSummary]:
        """Return the current project list, or ``[]`` if loading fails.

        Failures here collapse projects-tab rendering AND session grouping
        (every project-tagged conversation is rendered under Ungrouped until
        the next successful load). To keep users in the loop without spamming,
        this method fires ``ui.notify`` only on the healthy→failed transition
        tracked by ``self._projects_load_healthy``. Successful loads clear the
        flag so the next failure re-notifies.
        """
        try:
            projects = await self._project_store.list_projects_async()
        except (OSError, json.JSONDecodeError, ValidationError):
            logger.error("Failed to load projects", exc_info=True)
            if self._projects_load_healthy:
                self._projects_load_healthy = False
                ui.notify(
                    "Could not load projects — sessions may appear ungrouped. "
                    "Check logs.",
                    type="warning",
                )
            return []
        self._projects_load_healthy = True
        return projects

    async def _refresh_projects(self) -> None:
        if self._projects_container is None:
            return
        self._projects_container.clear()

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

    def _build_project_form_inputs(
        self,
        record: ProjectRecord | None = None,
        *,
        mark_prefix: str = "",
    ) -> tuple[ui.input, ui.input, ui.textarea]:
        """Build the three shared inputs for new/edit project dialogs.

        Returns ``(name, folder, instructions)`` widgets, pre-filled from
        ``record`` on edit. ``mark_prefix`` preserves the E2E markers
        (``new-project-name`` etc.) used by the existing new-project tests;
        edit dialog passes the empty default since it had no markers
        pre-F4 and adding them here would silently gate on tests that
        don't exist yet.
        """
        name_input = (
            ui.input("Name", value=record.name if record else "")
            .classes("w-full")
        )
        folder_input = (
            ui.input("Folder", value=record.folder if record else "")
            .classes("w-full")
        )
        instructions_input = (
            ui.textarea("Instructions", value=record.instructions if record else "")
            .classes("w-full")
            .props("rows=4")
        )
        if mark_prefix:
            name_input.mark(f"{mark_prefix}-name")
            folder_input.mark(f"{mark_prefix}-folder")
            instructions_input.mark(f"{mark_prefix}-instructions")
        return name_input, folder_input, instructions_input

    async def _persist_project_record(
        self, record: ProjectRecord, failure_message: str
    ) -> bool:
        """Save ``record`` via ``project_store.save``; return True iff saved.

        Centralizes the OSError → log + notify + False pattern that was
        duplicated across ``_create_project`` and ``_update_project``. The
        caller chooses the user-facing ``failure_message`` ("Failed to
        create project" vs "Failed to update project") so the toast reads
        naturally without a save-time enum.
        """
        try:
            await self._project_store.save(record)
        except OSError:
            logger.error("Failed to save project %s", record.id, exc_info=True)
            ui.notify(failure_message, type="warning")
            return False
        return True

    def _open_new_project_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("min-w-80"):
            ui.label("New Project").classes("text-h6")
            name_input, folder_input, instructions_input = (
                self._build_project_form_inputs(mark_prefix="new-project")
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def _save() -> None:
                    saved = await self._create_project(
                        name_input.value or "",
                        folder_input.value or "",
                        instructions_input.value or "",
                    )
                    if saved:
                        dialog.close()

                ui.button("Create", on_click=_save).mark("new-project-save")
        dialog.open()

    async def _create_project(
        self, name: str, folder: str, instructions: str
    ) -> bool:
        """Persist a new project; return True iff saved.

        False result tells the caller's dialog to stay open so the user can
        correct the validation or retry after a save failure without
        re-entering every field.
        """
        name = name.strip()
        folder = folder.strip()
        if not name or not folder:
            ui.notify("Name and folder are required", type="warning")
            return False
        record = ProjectRecord(
            id=uuid.uuid4().hex[:8],
            name=name,
            folder=folder,
            instructions=instructions,
        )
        if not await self._persist_project_record(
            record, "Failed to create project"
        ):
            return False
        await self._refresh_projects()
        return True

    async def _open_edit_project_dialog(self, project_id: str) -> None:
        try:
            record = await self._project_store.load_async(project_id)
        except ProjectLoadError:
            ui.notify("Project data is damaged — see logs", type="warning")
            return
        except Exception:
            logger.exception(
                "Unexpected failure opening edit dialog for %s", project_id
            )
            ui.notify("Could not open edit dialog — see logs", type="warning")
            return
        if record is None:
            ui.notify("Project not found", type="warning")
            return
        with ui.dialog() as dialog, ui.card().classes("min-w-80"):
            ui.label("Edit Project").classes("text-h6")
            name_input, folder_input, instructions_input = (
                self._build_project_form_inputs(record)
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def _save() -> None:
                    saved = await self._update_project(
                        record,
                        name_input.value or "",
                        folder_input.value or "",
                        instructions_input.value or "",
                    )
                    if saved:
                        dialog.close()

                ui.button("Save", on_click=_save).mark(f"save-project-{project_id}")
        dialog.open()

    async def _update_project(
        self,
        record: ProjectRecord,
        name: str,
        folder: str,
        instructions: str,
    ) -> bool:
        """Persist edits to an existing project; return True iff saved.

        False result tells the caller's dialog to stay open so the user can
        correct the validation or retry after a save failure without
        re-entering every field.
        """
        name = name.strip()
        folder = folder.strip()
        if not name or not folder:
            ui.notify("Name and folder are required", type="warning")
            return False
        updated = record.model_copy(
            update={"name": name, "folder": folder, "instructions": instructions}
        )
        if not await self._persist_project_record(
            updated, "Failed to update project"
        ):
            return False
        # If the active session belongs to this project, route a no-op
        # session switch through the callback so project_instructions
        # re-resolves via the layout-owned single source of truth
        # (`_apply_session_switch`). Direct mutation here would diverge
        # from that invariant — the whole reason layout owns the resolve.
        if self._session.project_id == record.id:
            self._on_session_switch(
                SessionSwitch(
                    session_id=self._session.id,
                    messages=self._session.messages,
                    project_id=self._session.project_id,
                )
            )
        await self._refresh_projects()
        await self._refresh_sessions()
        return True

    async def _open_delete_project_dialog(self, project_id: str) -> None:
        try:
            record = await self._project_store.load_async(project_id)
        except ProjectLoadError:
            ui.notify("Project data is damaged — see logs", type="warning")
            return
        except Exception:
            logger.exception(
                "Unexpected failure opening delete dialog for %s", project_id
            )
            ui.notify("Could not open delete dialog — see logs", type="warning")
            return
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
        delete_result = self._project_store.delete(project_id)
        if delete_result is ProjectDeleteResult.FAILED:
            ui.notify("Failed to delete project", type="warning")
            await self._refresh_projects()
            await self._refresh_sessions()
            return
        # Fall-through covers both DELETED and ALREADY_GONE:
        # desired-state-met, so clear active state. (ProjectStore.delete
        # logs the ALREADY_GONE breadcrumb for forensics.)
        if self._active_project_id == project_id:
            self._active_project_id = None
        if self._session.project_id == project_id:
            # Route through the switch callback so the layout owns both
            # project_id and project_instructions mutations in one spot.
            # Sends the same session_id + messages because we're detaching
            # from the project, not switching chats.
            self._on_session_switch(
                SessionSwitch(
                    session_id=self._session.id,
                    messages=self._session.messages,
                    project_id=None,
                )
            )
        await self._refresh_projects()
        await self._refresh_sessions()

    # --- Skills tab ---

    def _render_skills_tab(self) -> None:
        self._skills_container = (
            ui.column().classes("w-full gap-1").mark("skills-summary")
        )
        self._refresh_skills_summary()
        controller = self._session.controller
        if controller is not None and self._skills_unsubscribe is None:
            self._skills_unsubscribe = controller.subscribe(
                self._refresh_skills_summary
            )

    def _refresh_skills_summary(self) -> None:
        container = self._skills_container
        if container is None:
            return
        container.clear()
        with container:
            catalog = self._session.catalog
            if catalog is None:
                ui.label("No skills configured").classes(
                    "text-caption opacity-40"
                )
                return
            active_skills = [s for s in catalog.skills.values() if s.active]
            ui.label(f"Active ({len(active_skills)})").classes(
                "text-caption opacity-60"
            ).mark("skills-active-header")
            if active_skills:
                with ui.column().classes("w-full gap-0").mark(
                    "skills-active-list"
                ):
                    for skill in active_skills:
                        ui.label(skill.meta.name).classes(
                            "text-sm font-medium"
                        )
                        if skill.meta.description:
                            ui.label(skill.meta.description).classes(
                                "text-xs opacity-60"
                            )
            elif catalog.skills:
                ui.label("No active skills").classes(
                    "text-caption opacity-40"
                )
            else:
                ui.label("No skills discovered").classes(
                    "text-caption opacity-40"
                )
            ui.separator()
            manage_btn = ui.button(
                "Manage skills…", on_click=self._open_skills_manager
            ).classes("w-full").props("flat dense").mark("skills-manage-btn")
            if self._skills_manager is None or not self._skills_manager.available:
                manage_btn.disable()

    def _open_skills_manager(self) -> None:
        if self._skills_manager is not None:
            self._skills_manager.open()
