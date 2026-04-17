from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.models import Message
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.ui.sidebar import Sidebar
from tests.conftest import FakeProvider, make_skill, make_store


@pytest.mark.asyncio
async def test_should_render_session_and_skills_tabs(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)

    @ui.page("/test-tabs")
    async def page() -> None:
        sidebar = Sidebar(session, store, lambda *_: None)
        await sidebar.render()

    await user.open("/test-tabs")
    await user.should_see("Sessions")
    await user.should_see("Skills")


@pytest.mark.asyncio
async def test_should_show_new_chat_button(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)

    @ui.page("/test-new")
    async def page() -> None:
        sidebar = Sidebar(session, store, lambda *_: None)
        await sidebar.render()

    await user.open("/test-new")
    await user.should_see("New Chat")


@pytest.mark.asyncio
async def test_should_list_sessions_from_store(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    store.save_sync("s1", [Message(role="user", content="First chat")])
    store.save_sync("s2", [Message(role="user", content="Second chat")])

    session = Session(provider=FakeProvider())

    @ui.page("/test-list")
    async def page() -> None:
        sidebar = Sidebar(session, store, lambda *_: None)
        await sidebar.render()

    await user.open("/test-list")
    await user.should_see("First chat")
    await user.should_see("Second chat")


@pytest.mark.asyncio
async def test_should_show_skills_with_toggles(user: User) -> None:
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting skill", active=True),
        "search": make_skill("search", "Search skill", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    @ui.page("/test-skills")
    async def page() -> None:
        sidebar = Sidebar(session, None, lambda *_: None)
        await sidebar.render()

    await user.open("/test-skills")
    await user.should_see("greet")
    await user.should_see("Greeting skill")
    await user.should_see("search")
    await user.should_see("Search skill")


@pytest.mark.asyncio
async def test_should_show_no_skills_message(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/test-no-skills")
    async def page() -> None:
        sidebar = Sidebar(session, None, lambda *_: None)
        await sidebar.render()

    await user.open("/test-no-skills")
    await user.should_see("No skills configured")


@pytest.mark.asyncio
async def test_should_show_empty_catalog_message(user: User) -> None:
    catalog = SkillCatalog({})
    session = Session(provider=FakeProvider(), catalog=catalog)

    @ui.page("/test-empty-catalog")
    async def page() -> None:
        sidebar = Sidebar(session, None, lambda *_: None)
        await sidebar.render()

    await user.open("/test-empty-catalog")
    await user.should_see("No skills discovered")


@pytest.mark.asyncio
async def test_new_session_calls_callback(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Old message")]
    received: list[tuple[str, list]] = []

    def on_switch(new_id: str, new_messages: list[Message], new_project_id: str | None) -> None:
        received.append((new_id, new_messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-new-session")
    async def page() -> None:
        s = Sidebar(session, store, on_switch)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-new-session")
    await sidebar_ref[0]._new_session()

    assert len(received) == 1
    assert received[0][1] == []  # empty messages for new session


@pytest.mark.asyncio
async def test_load_session_calls_callback(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    store.save_sync("target", [Message(role="user", content="Loaded")])

    session = Session(provider=FakeProvider())
    received: list[tuple[str, list]] = []

    def on_switch(new_id: str, new_messages: list[Message], new_project_id: str | None) -> None:
        received.append((new_id, new_messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load")
    async def page() -> None:
        s = Sidebar(session, store, on_switch)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load")
    await sidebar_ref[0]._load_session("target")

    assert len(received) == 1
    assert received[0][0] == "target"
    assert received[0][1][0].content == "Loaded"


@pytest.mark.asyncio
async def test_load_nonexistent_session_does_not_switch(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    session = Session(provider=FakeProvider())
    original_id = session.id
    received: list[tuple[str, list]] = []

    def on_switch(new_id: str, new_messages: list[Message], new_project_id: str | None) -> None:
        received.append((new_id, new_messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-missing")
    async def page() -> None:
        s = Sidebar(session, store, on_switch)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load-missing")
    await sidebar_ref[0]._load_session("does-not-exist")

    assert len(received) == 0
    assert session.id == original_id


@pytest.mark.asyncio
async def test_toggle_skill(user: User) -> None:
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-toggle")
    sidebar_ref[0]._toggle_skill("greet", True)
    assert catalog.skills["greet"].active is True

    sidebar_ref[0]._toggle_skill("greet", False)
    assert catalog.skills["greet"].active is False


async def test_toggle_nonexistent_skill(user: User) -> None:
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle-fail")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-toggle-fail")
    # Toggling a nonexistent skill should not raise
    sidebar_ref[0]._toggle_skill("nonexistent", True)
    assert catalog.skills["greet"].active is False


# --- Error-handling coverage ---


async def test_refresh_sessions_handles_load_failure(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Cover sidebar.py:59-62: _refresh_sessions exception path."""
    store = make_store(tmp_path)
    store.list_conversations_async = AsyncMock(side_effect=RuntimeError("DB error"))

    session = Session(provider=FakeProvider())
    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-refresh-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None)
        sidebar_ref.append(s)
        await s.render()

    with caplog.at_level(logging.WARNING):
        await user.open("/test-refresh-fail")
    await user.should_see("Failed to load")
    assert "Failed to load conversations" in caplog.text


async def test_load_session_handles_exception(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Cover sidebar.py:84-87: _load_session exception path."""
    store = make_store(tmp_path)
    store.load_async = AsyncMock(side_effect=RuntimeError("Load failed"))

    session = Session(provider=FakeProvider())
    received: list[tuple[str, list]] = []

    def on_switch(new_id: str, new_messages: list[Message], new_project_id: str | None) -> None:
        received.append((new_id, new_messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-exception")
    async def page() -> None:
        s = Sidebar(session, store, on_switch)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load-exception")
    with caplog.at_level(logging.WARNING), patch(
        "stoiquent.ui.sidebar.ui.notify"
    ) as mock_notify:
        await sidebar_ref[0]._load_session("bad-id")

    assert len(received) == 0
    store.load_async.assert_called_once_with("bad-id")
    assert "Failed to load conversation" in caplog.text
    mock_notify.assert_called_once_with(
        "Could not load conversation", type="warning"
    )


async def test_load_session_with_none_store(user: User) -> None:
    """Cover sidebar.py:77: _load_session early return when store is None."""
    session = Session(provider=FakeProvider())
    received: list[tuple[str, list]] = []

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-none-store")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: received.append(("x", [])))
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load-none-store")
    await sidebar_ref[0]._load_session("any-id")

    assert len(received) == 0


async def test_load_session_saves_old_messages(
    user: User, tmp_path: Path
) -> None:
    """Cover sidebar.py:79: save_background called before switching sessions."""
    store = make_store(tmp_path)
    store.save_sync("target", [Message(role="user", content="Target")])
    store.save_background = Mock()

    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Old message")]
    original_id = session.id

    received: list[tuple[str, list]] = []

    def on_switch(new_id: str, new_messages: list[Message], new_project_id: str | None) -> None:
        received.append((new_id, new_messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-saves")
    async def page() -> None:
        s = Sidebar(session, store, on_switch)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load-saves")
    await sidebar_ref[0]._load_session("target")

    store.save_background.assert_called_once_with(
        original_id, [Message(role="user", content="Old message")], None
    )
    assert len(received) == 1
    assert received[0][0] == "target"


async def test_toggle_skill_notifies_on_failure(user: User) -> None:
    """Cover sidebar.py:128: notification when skill toggle fails."""
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=False),
    })
    catalog.activate = Mock(return_value=False)

    session = Session(provider=FakeProvider(), catalog=catalog)
    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle-fail-notify")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-toggle-fail-notify")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        sidebar_ref[0]._toggle_skill("greet", True)
    catalog.activate.assert_called_once_with("greet")
    mock_notify.assert_called_once_with(
        "Failed to activate skill 'greet'", type="warning"
    )


async def test_toggle_skill_notifies_on_deactivate_failure(user: User) -> None:
    """Cover sidebar.py:131: deactivate branch of toggle failure notification."""
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=True),
    })
    catalog.deactivate = Mock(return_value=False)

    session = Session(provider=FakeProvider(), catalog=catalog)
    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle-deactivate-fail")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-toggle-deactivate-fail")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        sidebar_ref[0]._toggle_skill("greet", False)
    catalog.deactivate.assert_called_once_with("greet")
    mock_notify.assert_called_once_with(
        "Failed to deactivate skill 'greet'", type="warning"
    )


async def test_new_session_saves_old_messages(
    user: User, tmp_path: Path
) -> None:
    """Cover sidebar.py:95-98: save_background called before new session."""
    store = make_store(tmp_path)
    store.save_background = Mock()

    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Unsaved work")]
    original_id = session.id

    received: list[tuple[str, list]] = []

    def on_switch(new_id: str, new_messages: list[Message], new_project_id: str | None) -> None:
        received.append((new_id, new_messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-new-saves")
    async def page() -> None:
        s = Sidebar(session, store, on_switch)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-new-saves")
    await sidebar_ref[0]._new_session()

    store.save_background.assert_called_once_with(
        original_id, [Message(role="user", content="Unsaved work")], None
    )
    assert len(received) == 1
    assert received[0][0] != original_id  # new session ID generated
    assert len(received[0][0]) == 8  # uuid hex[:8]
    assert received[0][1] == []  # new session has empty messages
