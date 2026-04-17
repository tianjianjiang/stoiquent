from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.models import Message
from stoiquent.ui.chat import ChatPanel
from stoiquent.ui.sidebar import Sidebar

if TYPE_CHECKING:
    from stoiquent.models import AppConfig
    from stoiquent.persistence import ConversationStore
    from stoiquent.projects import ProjectStore

logger = logging.getLogger(__name__)


async def render(
    session: Session,
    store: ConversationStore | None = None,
    config: AppConfig | None = None,
    project_store: ProjectStore | None = None,
) -> None:
    chat = ChatPanel(session, store)

    def on_session_switch(
        new_id: str, new_messages: list[Message], new_project_id: str | None
    ) -> None:
        _apply_session_switch(
            session, project_store, new_id, new_messages, new_project_id
        )
        chat.reload_messages()

    def on_provider_change(provider_name: str) -> None:
        if not _switch_provider(session, config, provider_name):
            return
        if session.messages and store is not None:
            store.save_background(session.id, session.messages, session.project_id)
        session.messages = []
        chat.reload_messages()
        ui.notify("Provider switched. Starting fresh conversation.")

    with ui.header().classes("items-center gap-4 px-4"):
        ui.label("Stoiquent").classes("text-h6 font-bold")
        ui.space()
        if config and config.providers:
            provider_names = list(config.providers.keys())
            ui.select(
                provider_names,
                value=config.default_provider,
                on_change=lambda e: on_provider_change(e.value),
            ).classes("w-40").props("dense").mark("provider-select")
        ui.label("Local LLM Agent").classes("text-caption opacity-60")

    with ui.splitter(value=20).classes("w-full h-screen") as splitter:
        with splitter.before:
            sidebar = Sidebar(session, store, on_session_switch)
            await sidebar.render()

        with splitter.after:
            chat.render()


def _load_project_instructions(
    project_store: ProjectStore | None, project_id: str | None
) -> str:
    """Return the project's instructions, or '' when the store/id is absent
    or the project cannot be loaded.

    ``ProjectStore.load`` absorbs its documented expected-failure set
    (missing file, I/O errors, corrupt JSON, schema errors) and returns
    ``None``; those route through the ``record is None`` branch. Any other
    exception is a contract violation and is logged at ERROR with traceback,
    then swallowed so a session switch is never blocked by a faulty project
    record.
    """
    if project_store is None or project_id is None:
        return ""
    try:
        record = project_store.load(project_id)
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
    new_id: str,
    new_messages: list[Message],
    new_project_id: str | None,
) -> None:
    """Update all session fields tied to the active conversation together.

    Keeps ``project_id`` and ``project_instructions`` consistent so a
    chat cannot retain stale instructions after switching to a session
    with no project or a different project. Instructions are resolved
    before any field is mutated, so a future load-failure that surfaced
    as a raise would leave the session untouched.
    """
    new_instructions = _load_project_instructions(project_store, new_project_id)
    session.id = new_id
    session.messages = new_messages
    session.project_id = new_project_id
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
