from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.skills.discovery import discover_skills
from stoiquent.ui.chat import ChatPanel
from stoiquent.ui.sidebar import Sidebar, SessionSwitch
from stoiquent.ui.skills_header import SkillsHeaderMenu
from stoiquent.ui.skills_manager import SkillsManager
from stoiquent.ui.theme import DarkModeToggle, apply_theme

if TYPE_CHECKING:
    from stoiquent.models import AppConfig
    from stoiquent.persistence import ConversationStore
    from stoiquent.projects import ProjectStore

logger = logging.getLogger(__name__)


async def render(
    session: Session,
    store: ConversationStore | None = None,
    config: AppConfig | None = None,
    *,
    project_store: ProjectStore,
) -> None:
    apply_theme()
    chat = ChatPanel(session, store)

    def on_session_switch(switch: SessionSwitch) -> None:
        _apply_session_switch(session, project_store, switch)
        chat.reload_messages()

    def on_provider_change(provider_name: str) -> None:
        if not _switch_provider(session, config, provider_name):
            return
        if session.messages and store is not None:
            store.save_background(session.id, session.messages, session.project_id)
        session.messages = []
        chat.reload_messages()
        ui.notify("Provider switched. Starting fresh conversation.")

    skills_manager = SkillsManager(
        session.controller,
        discover=(
            (lambda cfg=config.skills: discover_skills(cfg)) if config else None
        ),
    )

    with ui.header().classes("items-center gap-4 px-4"):
        ui.label("Stoiquent").classes("text-h6 font-bold")
        ui.space()
        DarkModeToggle()
        if config and config.providers:
            provider_names = list(config.providers.keys())
            ui.select(
                provider_names,
                value=config.default_provider,
                on_change=lambda e: on_provider_change(e.value),
            ).classes("w-40").props("dense").mark("provider-select")
        skills_header = SkillsHeaderMenu(
            session.controller, manager=skills_manager
        )
        skills_header.build()
        ui.label("Local LLM Agent").classes("text-caption opacity-60")

    skills_manager.build()

    with ui.splitter(value=20).classes("w-full h-screen") as splitter:
        with splitter.before:
            sidebar = Sidebar(
                session,
                store,
                on_session_switch,
                project_store,
                skills_manager=skills_manager,
            )
            await sidebar.render()

        with splitter.after:
            chat.render()

    _surface_startup_warnings(session)

    def _teardown_page() -> None:
        # Exception-isolate the teardowns: a misbehaving unsubscribe
        # callable must not prevent the sibling teardown from running, or
        # the "leak" the teardown was meant to plug survives silently.
        for label, teardown in (
            ("skills_manager", skills_manager.teardown),
            ("skills_header", skills_header.teardown),
            ("sidebar", sidebar.teardown),
        ):
            try:
                teardown()
            except Exception:
                logger.exception("Failed to tear down %s on disconnect", label)

    ui.context.client.on_disconnect(_teardown_page)


def _surface_startup_warnings(session: Session) -> None:
    """Drain queued startup warnings via ``ui.notify``, re-queueing any
    that fail to render so the next layout build retries them.

    ``consume_startup_warnings`` already drained ``session.startup_warnings``
    into a local snapshot, so an unhandled raise mid-loop would silently
    drop any unprocessed warnings — the user-facing message would be lost.
    Persistent + dismissable so a user who tabs away doesn't miss the
    signal. Extracted so this silent-failure recovery path is unit-testable
    without the NiceGUI ``User`` harness, which installs its own
    ``UserNotify`` and overrides monkeypatched ``ui.notify`` references.
    """
    for warning in session.consume_startup_warnings():
        try:
            ui.notify(
                warning,
                type="warning",
                multi_line=True,
                close_button="Dismiss",
                timeout=0,
            )
        except Exception:
            logger.exception("Failed to surface startup warning; re-queuing")
            session.startup_warnings.append(warning)


def _load_project_instructions(
    project_store: ProjectStore | None, project_id: str | None
) -> str:
    """Return the project's instructions, or '' when the store/id is absent,
    the project is missing, or its file is damaged.

    `ProjectStore.load` returns `None` for genuine absence and raises
    `ProjectLoadError` for corrupt/IO failures. `ProjectLoadError` is
    logged at WARNING, surfaced to the user via `ui.notify` (so they
    don't silently get an effectively-projectless session), and absorbed
    (returns `""`) so the session switch is never blocked. Any other
    exception is a contract violation: logged at ERROR with traceback,
    absorbed (returns `""`); the user sees no toast because it indicates
    a bug rather than an actionable data-damage condition.

    Note on UX asymmetry with sidebar dialog openers (which toast on
    both damaged and unexpected): dialogs can't proceed without a
    record, so silent-on-bug would look like a dead button; session
    switch falls through to a functional (if project-less) chat, so
    adding a toast here would fire on every switch after a single bug
    and drown real signal.
    """
    from stoiquent.projects import ProjectLoadError

    if project_store is None or project_id is None:
        return ""
    try:
        record = project_store.load(project_id)
    except ProjectLoadError:
        logger.warning(
            "Project %s exists but could not be loaded; using empty instructions",
            project_id,
        )
        ui.notify(
            "Project instructions unavailable — project file is damaged",
            type="warning",
        )
        return ""
    except Exception:
        logger.error(
            "Unexpected failure loading project instructions for %s",
            project_id,
            exc_info=True,
        )
        return ""
    if record is None:
        return ""
    return record.instructions


def _apply_session_switch(
    session: Session,
    project_store: ProjectStore | None,
    switch: SessionSwitch,
) -> None:
    """Update all session fields tied to the active conversation together.

    Keeps ``project_id`` and ``project_instructions`` consistent so a
    chat cannot retain stale instructions after switching to a session
    with no project or a different project. Instructions are resolved
    before any field is mutated, so a future load-failure that surfaced
    as a raise would leave the session untouched.
    """
    new_instructions = _load_project_instructions(project_store, switch.project_id)
    session.id = switch.session_id
    session.messages = switch.messages
    session.project_id = switch.project_id
    session.project_instructions = new_instructions


def _switch_provider(
    session: Session, config: AppConfig | None, provider_name: str
) -> bool:
    from stoiquent.llm.openai_compat import OpenAICompatProvider

    if config is None:
        return False
    prov_config = config.providers.get(provider_name)
    if prov_config is None:
        logger.warning("Provider config not found for %r", provider_name)
        ui.notify(f"Provider '{provider_name}' is not configured", type="negative")
        return False
    old_provider = session.provider
    session.provider = OpenAICompatProvider(prov_config)
    if hasattr(old_provider, "close"):

        def _log_close_error(t: asyncio.Task) -> None:
            if exc := t.exception():
                logger.warning("Failed to close old provider: %s", exc)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(old_provider.close())
            task.add_done_callback(_log_close_error)
        except RuntimeError:
            logger.warning("No event loop to close old provider")
    return True
