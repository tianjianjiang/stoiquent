from __future__ import annotations

from pathlib import Path

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

    def on_switch(new_id: str, new_messages: list[Message]) -> None:
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

    def on_switch(new_id: str, new_messages: list[Message]) -> None:
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

    def on_switch(new_id: str, new_messages: list[Message]) -> None:
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
