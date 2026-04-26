"""E2E tests for UI interaction using NiceGUI User fixture.

Uses the User fixture (NiceGUI's recommended approach) for fast,
reliable interactive testing without a browser. Covers: sending messages,
session switching, skills toggling, tab navigation, provider dropdown.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from unittest.mock import Mock

from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session

from stoiquent.models import Message, StreamChunk
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.ui import layout
from tests.conftest import (
    FakeProvider,
    make_project_store,
    make_skill,
    make_store,
    two_provider_config,
)


# --- Send message ---


async def test_send_message_shows_response(user: User, tmp_path: Path) -> None:
    chunks = [
        StreamChunk(content_delta="Hello from the agent!"),
        StreamChunk(finish_reason="stop"),
    ]
    session = Session(provider=FakeProvider(chunks=chunks))
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/")
    user.find(marker="chat-input").type("Hi there")
    user.find(marker="send-btn").click()
    await user.should_see("Hello from the agent!")


# --- Tab navigation ---


async def test_sidebar_tabs_navigation(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/")
    await user.should_see("Sessions")
    await user.should_see("Skills")
    await user.should_see("New Chat")

    # Click Skills tab
    user.find(marker="skills-tab").click()
    await user.should_see("No skills configured")

    # Click Sessions tab back
    user.find(marker="sessions-tab").click()
    await user.should_see("New Chat")


# --- Skills tab summary ---


async def test_skills_tab_shows_active_skills_only(
    user: User, tmp_path: Path
) -> None:
    """Sidebar Skills tab is the active-summary surface (per the
    three-surface design: Sidebar = active list, Header = quick toggles,
    Manager = full overlay). Inactive skills must NOT appear here — they
    live in the Manager overlay reachable via the "Manage skills…"
    button. The previous incarnation of this test asserted both active
    and inactive skills were rendered with toggles, which matched the
    old single-surface design that PR C/D/E replaced.
    """
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting skill", active=True),
        "search": make_skill("search", "Search skill", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/")
    user.find(marker="skills-tab").click()
    await user.should_see("Active (1)")
    await user.should_see("greet")
    await user.should_see("Greeting skill")
    await user.should_see("Manage skills")
    await user.should_not_see("search")
    await user.should_not_see("Search skill")


# --- Session list + load ---


async def test_session_list_renders(user: User, tmp_path: Path) -> None:
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    store.save_sync("s1", [Message(role="user", content="First chat")])
    store.save_sync("target", [
        Message(role="user", content="Loaded question"),
        Message(role="assistant", content="Loaded answer"),
    ])

    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, store, project_store=project_store)

    await user.open("/")
    await user.should_see("First chat")
    await user.should_see("Loaded question")


# --- New Chat triggers on_session_switch ---


async def test_new_chat_resets_session(user: User, tmp_path: Path) -> None:
    """Cover layout.py lines 29-31: on_session_switch closure via New Chat."""
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Old message")]

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, store, project_store=project_store)

    await user.open("/")
    user.find(marker="new-chat-btn").click()
    # Yield to event loop so NiceGUI's in-process async handler completes
    await asyncio.sleep(0)
    assert session.messages == []


# --- Provider dropdown ---


async def test_provider_change_clears_messages(user: User, tmp_path: Path) -> None:
    """Cover layout.py lines 34-40: on_provider_change closure."""
    config = two_provider_config(second="cloud-gpt")
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Before switch")]
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, config=config, project_store=project_store)

    await user.open("/")
    # NiceGUI's User fixture has no high-level API for changing ui.select
    # values, so we access the element directly via .elements and set_value().
    select_element = next(iter(user.find(marker="provider-select").elements))
    select_element.set_value("cloud-gpt")
    # set_value triggers on_provider_change synchronously via change handlers
    assert session.messages == []


async def test_provider_change_saves_messages(user: User, tmp_path: Path) -> None:
    """Cover layout.py:37: save_background called before clearing messages."""
    config = two_provider_config(second="cloud-gpt")
    store = make_store(tmp_path)
    store.save_background = Mock()
    project_store = make_project_store(tmp_path)

    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Save me")]
    original_id = session.id

    @ui.page("/")
    async def page() -> None:
        await layout.render(
            session, store, config=config, project_store=project_store
        )

    await user.open("/")
    select_element = next(iter(user.find(marker="provider-select").elements))
    select_element.set_value("cloud-gpt")

    store.save_background.assert_called_once_with(
        original_id, [Message(role="user", content="Save me")], None
    )
    assert session.messages == []


async def test_provider_dropdown_renders_with_config(
    user: User, tmp_path: Path
) -> None:
    config = two_provider_config(second="cloud-gpt")
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, config=config, project_store=project_store)

    await user.open("/")
    await user.should_see("Stoiquent")
    await user.should_see("local-qwen")
    await user.should_see("Local LLM Agent")
