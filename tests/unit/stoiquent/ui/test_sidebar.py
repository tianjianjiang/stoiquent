from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.models import Message
from stoiquent.projects import ProjectDeleteResult, ProjectRecord
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.ui.sidebar import SessionSwitch, Sidebar
from tests.conftest import (
    FakeProvider,
    make_project_store,
    make_skill,
    make_store,
)


# --- SessionSwitch type contract ---


def test_session_switch_is_frozen() -> None:
    """Locks item-3 invariant: a dispatched SessionSwitch can't be mutated
    mid-apply. Removing `frozen=True` would let a receiver alter the
    intent (e.g. flip project_id after instructions were resolved),
    silently re-enabling exactly the class of bugs this dataclass blocks.
    """
    switch = SessionSwitch(session_id="s", messages=[], project_id=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        switch.session_id = "hacked"  # type: ignore[misc]


def test_session_switch_field_names_and_order_pinned() -> None:
    """Pin the field order so a future refactor can't silently reintroduce
    the positional `(str, list, str | None)` form by renaming/reordering.
    """
    fields = dataclasses.fields(SessionSwitch)
    assert [f.name for f in fields] == ["session_id", "messages", "project_id"]


def test_session_switch_rejects_empty_session_id() -> None:
    """The only enforced field-level invariant — session_id must be
    non-empty. Layout relies on this to keep session.id meaningful."""
    with pytest.raises(ValueError, match="session_id must be non-empty"):
        SessionSwitch(session_id="", messages=[], project_id=None)


@pytest.mark.asyncio
async def test_should_render_session_and_skills_tabs(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)

    @ui.page("/test-tabs")
    async def page() -> None:
        sidebar = Sidebar(session, store, lambda *_: None, make_project_store(tmp_path))
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
        sidebar = Sidebar(session, store, lambda *_: None, make_project_store(tmp_path))
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
        sidebar = Sidebar(session, store, lambda *_: None, make_project_store(tmp_path))
        await sidebar.render()

    await user.open("/test-list")
    await user.should_see("First chat")
    await user.should_see("Second chat")


@pytest.mark.asyncio
async def test_should_show_skills_with_toggles(user: User, tmp_path: Path) -> None:
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting skill", active=True),
        "search": make_skill("search", "Search skill", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    @ui.page("/test-skills")
    async def page() -> None:
        sidebar = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
        await sidebar.render()

    await user.open("/test-skills")
    await user.should_see("greet")
    await user.should_see("Greeting skill")
    await user.should_see("search")
    await user.should_see("Search skill")


@pytest.mark.asyncio
async def test_should_show_no_skills_message(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/test-no-skills")
    async def page() -> None:
        sidebar = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
        await sidebar.render()

    await user.open("/test-no-skills")
    await user.should_see("No skills configured")


@pytest.mark.asyncio
async def test_should_show_empty_catalog_message(user: User, tmp_path: Path) -> None:
    catalog = SkillCatalog({})
    session = Session(provider=FakeProvider(), catalog=catalog)

    @ui.page("/test-empty-catalog")
    async def page() -> None:
        sidebar = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
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

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-new-session")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, make_project_store(tmp_path))
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

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, make_project_store(tmp_path))
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

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-missing")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, make_project_store(tmp_path))
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load-missing")
    await sidebar_ref[0]._load_session("does-not-exist")

    assert len(received) == 0
    assert session.id == original_id


@pytest.mark.asyncio
async def test_toggle_skill(user: User, tmp_path: Path) -> None:
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-toggle")
    sidebar_ref[0]._toggle_skill("greet", True)
    assert catalog.skills["greet"].active is True

    sidebar_ref[0]._toggle_skill("greet", False)
    assert catalog.skills["greet"].active is False


async def test_toggle_nonexistent_skill(user: User, tmp_path: Path) -> None:
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle-fail")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
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
    """_refresh_sessions catches expected I/O and schema errors, emits a
    warning log, and now also notifies the user (not just the sidebar label).
    """
    store = make_store(tmp_path)
    store.list_conversations_async = AsyncMock(side_effect=OSError("DB error"))

    session = Session(provider=FakeProvider())
    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-refresh-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, make_project_store(tmp_path))
        sidebar_ref.append(s)
        await s.render()

    with caplog.at_level(logging.WARNING):
        await user.open("/test-refresh-fail")
    await user.should_see("Failed to load")
    assert "Failed to load conversations" in caplog.text


async def test_load_session_handles_exception(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """_load_session catches expected I/O and schema errors, logs a
    warning, and notifies the user."""
    store = make_store(tmp_path)
    store.load_async = AsyncMock(side_effect=OSError("Load failed"))

    session = Session(provider=FakeProvider())
    received: list[tuple[str, list]] = []

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-exception")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, make_project_store(tmp_path))
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


async def test_load_session_with_none_store(user: User, tmp_path: Path) -> None:
    """Cover sidebar.py:77: _load_session early return when store is None."""
    session = Session(provider=FakeProvider())
    received: list[tuple[str, list]] = []

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-none-store")
    async def page() -> None:
        s = Sidebar(
            session,
            None,
            lambda *_: received.append(("x", [])),
            make_project_store(tmp_path),
        )
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

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-load-saves")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, make_project_store(tmp_path))
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-load-saves")
    await sidebar_ref[0]._load_session("target")

    store.save_background.assert_called_once_with(
        original_id, [Message(role="user", content="Old message")], None
    )
    assert len(received) == 1
    assert received[0][0] == "target"


async def test_toggle_skill_notifies_on_failure(user: User, tmp_path: Path) -> None:
    """Cover sidebar.py:128: notification when skill toggle fails."""
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=False),
    })
    catalog.activate = Mock(return_value=False)

    session = Session(provider=FakeProvider(), catalog=catalog)
    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle-fail-notify")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-toggle-fail-notify")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        sidebar_ref[0]._toggle_skill("greet", True)
    catalog.activate.assert_called_once_with("greet")
    mock_notify.assert_called_once_with(
        "Failed to activate skill 'greet'", type="warning"
    )


async def test_toggle_skill_notifies_on_deactivate_failure(user: User, tmp_path: Path) -> None:
    """Cover sidebar.py:131: deactivate branch of toggle failure notification."""
    catalog = SkillCatalog({
        "greet": make_skill("greet", "Greeting", active=True),
    })
    catalog.deactivate = Mock(return_value=False)

    session = Session(provider=FakeProvider(), catalog=catalog)
    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-toggle-deactivate-fail")
    async def page() -> None:
        s = Sidebar(session, None, lambda *_: None, make_project_store(tmp_path))
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

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-new-saves")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, make_project_store(tmp_path))
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


# --- Projects tab ---


@pytest.mark.asyncio
async def test_projects_tab_renders(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    @ui.page("/test-projects-tab")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    await user.open("/test-projects-tab")
    await user.should_see("Projects")
    await user.should_see("+ New Project")
    await user.should_see("No projects yet")


@pytest.mark.asyncio
async def test_projects_tab_lists_existing_projects(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )
    project_store.save_sync(
        ProjectRecord(id="p2", name="Beta", folder="/tmp/b", instructions="")
    )

    @ui.page("/test-projects-list")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    await user.open("/test-projects-list")
    await user.should_see("Alpha")
    await user.should_see("Beta")


@pytest.mark.asyncio
async def test_create_project_persists_and_refreshes(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-create-project")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-create-project")
    saved = await sidebar_ref[0]._create_project(
        "MyProj", "/tmp/myproj", "Be concise."
    )

    assert saved is True
    projects = project_store.list_projects()
    assert len(projects) == 1
    assert projects[0].name == "MyProj"
    loaded = project_store.load(projects[0].id)
    assert loaded is not None
    assert loaded.instructions == "Be concise."


@pytest.mark.asyncio
async def test_create_project_rejects_blank_fields(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-create-blank")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-create-blank")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        saved = await sidebar_ref[0]._create_project("", "/tmp/x", "")
    assert saved is False
    mock_notify.assert_called_once_with(
        "Name and folder are required", type="warning"
    )
    assert project_store.list_projects() == []


@pytest.mark.asyncio
async def test_create_project_handles_save_failure(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save = AsyncMock(side_effect=OSError("disk full"))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-create-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-create-fail")
    with caplog.at_level(logging.ERROR), patch(
        "stoiquent.ui.sidebar.ui.notify"
    ) as mock_notify:
        saved = await sidebar_ref[0]._create_project("P", "/tmp/p", "")
    assert saved is False
    mock_notify.assert_called_once_with("Failed to create project", type="warning")
    assert "Failed to save project" in caplog.text
    caplog.clear()


@pytest.mark.asyncio
async def test_update_project_saves_and_refreshes_active_session(
    user: User, tmp_path: Path
) -> None:
    """Updating a project whose record matches the active session routes
    the refresh through the session-switch callback (item 4: layout owns
    the project_id/project_instructions invariant). Uses the real
    `_apply_session_switch` so end-to-end refresh behavior is covered.
    """
    from stoiquent.ui.layout import _apply_session_switch

    session = Session(provider=FakeProvider())
    session.project_id = "p1"
    session.project_instructions = "old"
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    record = ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="old")
    project_store.save_sync(record)

    def on_switch(switch: SessionSwitch) -> None:
        _apply_session_switch(session, project_store, switch)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-update-project")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-update-project")
    saved = await sidebar_ref[0]._update_project(
        record, "Alpha Renamed", "/tmp/a", "new instructions"
    )

    assert saved is True
    refreshed = project_store.load("p1")
    assert refreshed is not None
    assert refreshed.name == "Alpha Renamed"
    assert refreshed.instructions == "new instructions"
    assert session.project_instructions == "new instructions"


@pytest.mark.asyncio
async def test_update_project_rejects_blank(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    record = ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    project_store.save_sync(record)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-update-blank")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-update-blank")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        saved = await sidebar_ref[0]._update_project(record, "", "/tmp/a", "")
    assert saved is False
    mock_notify.assert_called_once_with(
        "Name and folder are required", type="warning"
    )


@pytest.mark.asyncio
async def test_update_project_handles_save_failure(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    record = ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    project_store.save_sync(record)
    project_store.save = AsyncMock(side_effect=OSError("disk"))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-update-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-update-fail")
    with caplog.at_level(logging.ERROR), patch(
        "stoiquent.ui.sidebar.ui.notify"
    ) as mock_notify:
        saved = await sidebar_ref[0]._update_project(record, "New", "/tmp/a", "")
    assert saved is False
    mock_notify.assert_called_once_with("Failed to update project", type="warning")
    # Log message now uniformly "Failed to save project %s" since F4
    # consolidated the log+notify pair into _persist_project_record.
    assert "Failed to save project p1" in caplog.text
    caplog.clear()


@pytest.mark.asyncio
async def test_update_project_leaves_unrelated_active_session_untouched(
    user: User, tmp_path: Path
) -> None:
    """False-branch regression for `if self._session.project_id == record.id`
    in `_update_project`. Editing project B while the active session is
    bound to project A must NOT route a SessionSwitch nor alter A's
    instructions. Pre-F4 only the TRUE branch was covered, so a typo
    flipping `==` to `!=` would silently clobber unrelated session state
    on every project edit.
    """
    session = Session(provider=FakeProvider())
    session.project_id = "projA"
    session.project_instructions = "A-only guidance"
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    rec_a = ProjectRecord(
        id="projA", name="A", folder="/tmp/a", instructions="A-only guidance"
    )
    rec_b = ProjectRecord(
        id="projB", name="B", folder="/tmp/b", instructions="B-only"
    )
    project_store.save_sync(rec_a)
    project_store.save_sync(rec_b)

    switches: list[SessionSwitch] = []

    def on_switch(switch: SessionSwitch) -> None:
        switches.append(switch)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-update-unrelated")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-update-unrelated")
    saved = await sidebar_ref[0]._update_project(
        rec_b, "B Renamed", "/tmp/b", "B-new-instructions"
    )

    assert saved is True
    # B's record was updated…
    refreshed = project_store.load("projB")
    assert refreshed is not None
    assert refreshed.name == "B Renamed"
    assert refreshed.instructions == "B-new-instructions"
    # …but the active session (bound to A) was not re-routed.
    assert switches == []
    assert session.project_id == "projA"
    assert session.project_instructions == "A-only guidance"


@pytest.mark.asyncio
async def test_delete_project_cascades_conversations(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    session.project_id = "p1"
    session.project_instructions = "hi"
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="p1 chat")], project_id="p1")
    store.save_sync("c2", [Message(role="user", content="p2 chat")], project_id="p2")
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="hi")
    )
    project_store.save_sync(
        ProjectRecord(id="p2", name="Beta", folder="/tmp/b", instructions="")
    )

    switches: list[SessionSwitch] = []

    def on_switch(switch: SessionSwitch) -> None:
        switches.append(switch)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-cascade")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, project_store)
        s._active_project_id = "p1"
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-cascade")
    await sidebar_ref[0]._delete_project("p1")

    assert project_store.load("p1") is None
    assert project_store.load("p2") is not None
    remaining_ids = {s.id for s in store.list_conversations()}
    assert remaining_ids == {"c2"}
    # Session mutation is routed through the switch callback (layout owns
    # project_id / project_instructions); the test observes the intent.
    assert len(switches) == 1
    assert switches[0].project_id is None
    assert switches[0].session_id == session.id
    assert sidebar_ref[0]._active_project_id is None


@pytest.mark.asyncio
async def test_delete_project_aborts_on_cascade_failure(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.delete_by_project_async = AsyncMock(side_effect=OSError("io"))
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-cascade-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-cascade-fail")
    with caplog.at_level(logging.ERROR), patch(
        "stoiquent.ui.sidebar.ui.notify"
    ) as mock_notify:
        await sidebar_ref[0]._delete_project("p1")

    assert project_store.load("p1") is not None
    mock_notify.assert_called_once_with(
        "Failed to delete project conversations", type="warning"
    )
    assert "Failed to cascade-delete conversations" in caplog.text
    caplog.clear()


@pytest.mark.asyncio
async def test_delete_project_aborts_on_partial_cascade(
    user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per user requirement (no orphan sessions), a cascade with ANY
    unlink failure must abort before the project record is deleted, so
    the delete is retryable."""
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="a")], project_id="p1")
    store.save_sync("c2", [Message(role="user", content="b")], project_id="p1")
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    real_unlink = Path.unlink

    def flaky_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "c2.json":
            raise PermissionError("locked")
        real_unlink(self)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-partial")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-partial")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._delete_project("p1")

    # Project record survives (retry anchor); c2 survives (unlink failed).
    assert project_store.load("p1") is not None
    assert (tmp_path / "conversations" / "c2.json").exists()
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    message = args[0]
    assert "unlink_failed=1" in message
    assert "deleted 1" in message
    assert "retry after the transient error clears" in message
    assert kwargs == {"type": "warning"}
    caplog.clear()


@pytest.mark.asyncio
async def test_delete_project_aborts_on_unreadable_conversation(
    user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cascade abort from ``skipped_unreadable`` must route through the
    structural (repair-or-remove) guidance branch, not the transient-retry
    one. A regression that collapses the retriable predicate to
    ``unlink_failed > 0`` would silently mis-advise the user."""
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="a")], project_id="p1")
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    real_read = Path.read_text

    def flaky_read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "c1.json":
            raise PermissionError("denied")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-unreadable")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-unreadable")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._delete_project("p1")

    assert project_store.load("p1") is not None
    message = mock_notify.call_args.args[0]
    assert "unreadable=1" in message
    assert "repair or remove the offending files" in message
    caplog.clear()


@pytest.mark.asyncio
async def test_delete_project_aborts_on_corrupt_conversation(
    user: User, tmp_path: Path
) -> None:
    """Cascade abort from skipped_unparseable must not report
    ``0 conversation(s)`` — the user needs to know the blocker is a
    corrupt file, not a failed unlink."""
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="a")], project_id="p1")
    # Plant a corrupt JSON file in the conversations dir so
    # delete_by_project increments skipped_unparseable and aborts.
    (tmp_path / "conversations" / "corrupt.json").write_text("{not json", encoding="utf-8")

    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-corrupt")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-corrupt")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._delete_project("p1")

    # Project kept so the user can fix the corrupt file and retry.
    assert project_store.load("p1") is not None
    mock_notify.assert_called_once()
    message = mock_notify.call_args.args[0]
    assert "unparseable=1" in message
    assert "repair or remove the offending files" in message


@pytest.mark.asyncio
async def test_delete_project_handles_record_delete_failure(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )
    project_store.delete = Mock(return_value=ProjectDeleteResult.FAILED)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-record-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-record-fail")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._delete_project("p1")

    mock_notify.assert_called_once_with("Failed to delete project", type="warning")


@pytest.mark.asyncio
async def test_delete_project_clears_active_state_on_already_gone(
    user: User, tmp_path: Path
) -> None:
    """Tri-state contract: ALREADY_GONE is desired-state-met; active state
    must still clear (race-with-concurrent-delete or phantom entry).
    Regression guard — a 'simplification' of the FAILED check to
    `is not DELETED` would incorrectly surface a failure toast AND skip
    the active-state clear for a desired-state-met outcome.

    The INFO breadcrumb for ALREADY_GONE is owned by ProjectStore.delete
    (not the sidebar), and is locked by
    test_delete_logs_breadcrumb_on_already_gone in test_projects.py —
    so this test no longer needs caplog."""
    from stoiquent.ui.layout import _apply_session_switch

    session = Session(provider=FakeProvider())
    session.project_id = "p1"
    session.project_instructions = "x"
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )
    project_store.delete = Mock(return_value=ProjectDeleteResult.ALREADY_GONE)

    switches: list[SessionSwitch] = []

    def on_switch(switch: SessionSwitch) -> None:
        switches.append(switch)
        # Wire the real resolver so the end-to-end side effect of item 4
        # (routing mutations through layout's single source of truth) is
        # also covered here, not only in test_layout.
        _apply_session_switch(session, project_store, switch)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-already-gone")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, project_store)
        s._active_project_id = "p1"
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-already-gone")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._delete_project("p1")

    mock_notify.assert_not_called()
    assert sidebar_ref[0]._active_project_id is None
    # Callback invoked with the correct intent…
    assert len(switches) == 1
    assert switches[0].project_id is None
    assert switches[0].session_id == session.id
    # …and the real `_apply_session_switch` cleared session state end-to-end.
    assert session.project_id is None
    assert session.project_instructions == ""


@pytest.mark.asyncio
async def test_edit_dialog_notifies_on_unexpected_load_exception(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Generic exceptions (not ProjectLoadError) escaping load_async
    must still reach the user, not silently abort the dialog."""
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    async def _raise(project_id: str) -> None:
        raise RuntimeError(f"unexpected for {project_id}")

    project_store.load_async = _raise  # type: ignore[method-assign]

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-edit-unexpected")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-edit-unexpected")
    with caplog.at_level(logging.ERROR, logger="stoiquent.ui.sidebar"):
        with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
            await sidebar_ref[0]._open_edit_project_dialog("any")
    mock_notify.assert_called_once_with(
        "Could not open edit dialog — see logs", type="warning"
    )
    caplog.clear()


@pytest.mark.asyncio
async def test_delete_dialog_notifies_on_unexpected_load_exception(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    async def _raise(project_id: str) -> None:
        raise RuntimeError(f"unexpected for {project_id}")

    project_store.load_async = _raise  # type: ignore[method-assign]

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-unexpected")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-unexpected")
    with caplog.at_level(logging.ERROR, logger="stoiquent.ui.sidebar"):
        with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
            await sidebar_ref[0]._open_delete_project_dialog("any")
    mock_notify.assert_called_once_with(
        "Could not open delete dialog — see logs", type="warning"
    )
    caplog.clear()


@pytest.mark.asyncio
async def test_set_active_project_changes_state_and_refreshes(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )
    project_store.save_sync(
        ProjectRecord(id="p2", name="Beta", folder="/tmp/b", instructions="")
    )

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-set-active")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-set-active")
    sb = sidebar_ref[0]

    await sb._set_active_project("p1")
    assert sb._active_project_id == "p1"
    # Refresh must have re-rendered — otherwise the highlight is invisible.
    assert sb._projects_container is not None
    rendered = _collect_row_classes(sb._projects_container)
    assert any("bg-blue-50" in c for c in rendered)

    await sb._set_active_project(None)
    assert sb._active_project_id is None
    rendered = _collect_row_classes(sb._projects_container)
    assert not any("bg-blue-50" in c for c in rendered)


def _collect_row_classes(container: ui.column) -> list[str]:
    classes: list[str] = []
    for descendant in container.descendants():
        cls = getattr(descendant, "_classes", None)
        if cls is None:
            continue
        classes.append(" ".join(cls) if isinstance(cls, list) else str(cls))
    return classes


@pytest.mark.asyncio
async def test_new_session_with_no_active_project_passes_none(
    user: User, tmp_path: Path
) -> None:
    """Pairs with ``test_new_session_inherits_active_project``: when no
    project is active, a new chat must NOT sticky-inherit the previous
    session's project_id."""
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    session = Session(provider=FakeProvider())
    session.project_id = "stale"

    received: list[tuple[str, list, str | None]] = []

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages, switch.project_id))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-new-no-active")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-new-no-active")
    assert sidebar_ref[0]._active_project_id is None
    await sidebar_ref[0]._new_session()

    assert len(received) == 1
    assert received[0][2] is None


@pytest.mark.asyncio
async def test_new_session_inherits_active_project(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    session = Session(provider=FakeProvider())

    received: list[tuple[str, list, str | None]] = []

    def on_switch(switch: SessionSwitch) -> None:
        received.append((switch.session_id, switch.messages, switch.project_id))

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-new-inherits")
    async def page() -> None:
        s = Sidebar(session, store, on_switch, project_store)
        s._active_project_id = "proj1"
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-new-inherits")
    await sidebar_ref[0]._new_session()

    assert len(received) == 1
    assert received[0][2] == "proj1"


@pytest.mark.asyncio
async def test_sessions_tab_groups_by_project(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    store.save_sync("a1", [Message(role="user", content="Alpha-chat")], project_id="p1")
    store.save_sync("b1", [Message(role="user", content="Beta-chat")], project_id="p2")
    store.save_sync("c1", [Message(role="user", content="Loose-chat")])
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )
    project_store.save_sync(
        ProjectRecord(id="p2", name="Beta", folder="/tmp/b", instructions="")
    )
    session = Session(provider=FakeProvider())

    @ui.page("/test-group-sessions")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    await user.open("/test-group-sessions")
    await user.should_see("Alpha")
    await user.should_see("Beta")
    await user.should_see("Ungrouped")
    await user.should_see("Alpha-chat")
    await user.should_see("Beta-chat")
    await user.should_see("Loose-chat")


@pytest.mark.asyncio
async def test_delete_unrelated_project_preserves_active_state(
    user: User, tmp_path: Path
) -> None:
    """Deleting project B must NOT clear active-state/session-state tied to
    project A. Locks the negative of `test_delete_project_cascades_conversations`.
    """
    session = Session(provider=FakeProvider())
    session.project_id = "p1"
    session.project_instructions = "stay"
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="stay")
    )
    project_store.save_sync(
        ProjectRecord(id="p2", name="Beta", folder="/tmp/b", instructions="")
    )

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-unrelated")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        s._active_project_id = "p1"
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-unrelated")
    await sidebar_ref[0]._delete_project("p2")

    assert sidebar_ref[0]._active_project_id == "p1"
    assert session.project_id == "p1"
    assert session.project_instructions == "stay"
    assert project_store.load("p1") is not None
    assert project_store.load("p2") is None


@pytest.mark.asyncio
async def test_sessions_tab_mixes_null_and_orphan_under_ungrouped(
    user: User, tmp_path: Path
) -> None:
    """Both project_id=None and project_id pointing at a deleted project
    must render together under the single Ungrouped header."""
    store = make_store(tmp_path)
    store.save_sync(
        "real", [Message(role="user", content="real-live")], project_id="live"
    )
    store.save_sync("loose", [Message(role="user", content="loose-chat")])
    store.save_sync(
        "orphan", [Message(role="user", content="orphan-chat")], project_id="gone"
    )
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="live", name="Live", folder="/tmp/live", instructions="")
    )
    session = Session(provider=FakeProvider())

    @ui.page("/test-group-mixed")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    await user.open("/test-group-mixed")
    await user.should_see("Live")
    await user.should_see("real-live")
    await user.should_see("Ungrouped")
    await user.should_see("loose-chat")
    await user.should_see("orphan-chat")


@pytest.mark.asyncio
async def test_sessions_tab_orphans_land_in_ungrouped(
    user: User, tmp_path: Path
) -> None:
    store = make_store(tmp_path)
    store.save_sync(
        "orphan", [Message(role="user", content="orphan-chat")], project_id="gone"
    )
    project_store = make_project_store(tmp_path)
    session = Session(provider=FakeProvider())

    @ui.page("/test-group-orphan")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    await user.open("/test-group-orphan")
    await user.should_see("Ungrouped")
    await user.should_see("orphan-chat")


@pytest.mark.asyncio
async def test_user_named_ungrouped_project_renders_distinct_from_bucket(
    user: User, tmp_path: Path
) -> None:
    """Locks item 14: a user who names a project literally "Ungrouped" gets a
    distinct header from the sessions-without-a-project bucket. Before the
    em-dash prefix the two groups shared a header and read as a single list.

    Asserts header-text ordering so a bug that dropped the em-dash prefix
    (collapsing both groups into one "Ungrouped" header) would be caught —
    `should_see` alone matches substrings and can't distinguish the two.
    """
    store = make_store(tmp_path)
    store.save_sync(
        "tagged",
        [Message(role="user", content="tagged-chat")],
        project_id="p1",
    )
    store.save_sync("loose", [Message(role="user", content="loose-chat")])
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(
            id="p1", name="Ungrouped", folder="/tmp/ung", instructions=""
        )
    )
    session = Session(provider=FakeProvider())

    @ui.page("/test-ungrouped-collision")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    await user.open("/test-ungrouped-collision")
    # The literal project name still appears (for the p1 group).
    await user.should_see("Ungrouped")
    # The bucket header carries the em-dash prefix, distinguishing it.
    await user.should_see("— Ungrouped")
    await user.should_see("tagged-chat")
    await user.should_see("loose-chat")

    # A bug that dropped the em-dash prefix would collapse both groups
    # under one "Ungrouped" header; lock the distinct bucket label
    # precisely-once. The plain "Ungrouped" may appear multiple times
    # (projects tab row + sessions tab group header), which is fine.
    rendered_text = [el.text for el in user.find("Ungrouped").elements]
    bucket_labels = [t for t in rendered_text if t and t.startswith("— ")]
    assert bucket_labels == ["— Ungrouped"]
    assert any(t == "Ungrouped" for t in rendered_text)


@pytest.mark.asyncio
async def test_refresh_projects_handles_list_failure(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.list_projects_async = AsyncMock(side_effect=OSError("io"))

    @ui.page("/test-refresh-proj-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()

    with caplog.at_level(logging.ERROR):
        await user.open("/test-refresh-proj-fail")
    await user.should_see("No projects yet")
    assert "Failed to load projects" in caplog.text
    caplog.clear()


@pytest.mark.asyncio
async def test_list_projects_safe_notifies_once_until_recovery(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Locks item 11: a failing ProjectStore surfaces ONE toast per
    healthy→failed transition. Silent re-bucketing during a sustained failure
    was the pre-F2 behavior that left users without a signal.

    Drives `_list_projects_safe` directly instead of going through render,
    so the assertion count doesn't silently drift if render's internal
    refresh sequence changes.
    """
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.list_projects_async = AsyncMock(side_effect=OSError("io"))
    s = Sidebar(session, store, lambda *_: None, project_store)

    with caplog.at_level(logging.ERROR), patch(
        "stoiquent.ui.sidebar.ui.notify"
    ) as mock_notify:
        # Consecutive successes (idempotent: no notify on either call).
        project_store.list_projects_async = AsyncMock(return_value=[])
        await s._list_projects_safe()
        await s._list_projects_safe()
        assert mock_notify.call_count == 0

        # First failure: healthy→failed transition fires one notify.
        project_store.list_projects_async = AsyncMock(side_effect=OSError("io"))
        await s._list_projects_safe()
        assert mock_notify.call_count == 1

        # Second failure: flag already flipped, no re-notify.
        await s._list_projects_safe()
        assert mock_notify.call_count == 1

        # Recover: successful load clears the flag without notifying.
        project_store.list_projects_async = AsyncMock(return_value=[])
        await s._list_projects_safe()
        assert mock_notify.call_count == 1

        # Re-fail: healthy→failed transition fires again.
        project_store.list_projects_async = AsyncMock(side_effect=OSError("io2"))
        await s._list_projects_safe()
        assert mock_notify.call_count == 2
    caplog.clear()


@pytest.mark.asyncio
async def test_edit_dialog_notifies_when_project_missing(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-edit-missing")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-edit-missing")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._open_edit_project_dialog("missing")
    mock_notify.assert_called_once_with("Project not found", type="warning")


@pytest.mark.asyncio
async def test_delete_dialog_notifies_when_project_missing(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-missing")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-missing")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._open_delete_project_dialog("missing")
    mock_notify.assert_called_once_with("Project not found", type="warning")


@pytest.mark.asyncio
async def test_edit_dialog_notifies_when_project_damaged(
    user: User, tmp_path: Path
) -> None:
    """Tri-state contract: a corrupt project file is 'damaged', not 'not found'."""
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    (tmp_path / "projects" / "bad.json").write_text("{corrupt", encoding="utf-8")

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-edit-damaged")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-edit-damaged")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._open_edit_project_dialog("bad")
    mock_notify.assert_called_once_with(
        "Project data is damaged — see logs", type="warning"
    )


@pytest.mark.asyncio
async def test_delete_dialog_notifies_when_project_damaged(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    (tmp_path / "projects" / "bad.json").write_text("{corrupt", encoding="utf-8")

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-damaged")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-delete-damaged")
    with patch("stoiquent.ui.sidebar.ui.notify") as mock_notify:
        await sidebar_ref[0]._open_delete_project_dialog("bad")
    mock_notify.assert_called_once_with(
        "Project data is damaged — see logs", type="warning"
    )


@pytest.mark.asyncio
async def test_count_conversations_returns_zero_when_no_conversation_store(
    user: User, tmp_path: Path
) -> None:
    """Contract lock: no conversation store means 0 conversations
    definitively, not 'unknown'. Distinguishes the no-store case (render
    'will also delete 0') from the read-failure case (render 'count
    unavailable'). See `test_count_conversations_handles_exception` for
    the None-return counterpart."""
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-count-no-store")
    async def page() -> None:
        s = Sidebar(session, store=None, on_session_switch=lambda *_: None,
                    project_store=project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-count-no-store")
    assert sidebar_ref[0]._count_conversations_for_project("p1") == 0


@pytest.mark.asyncio
async def test_count_conversations_handles_exception(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.list_conversations = Mock(side_effect=OSError("io"))
    project_store = make_project_store(tmp_path)

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-count-fail")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        sidebar_ref.append(s)
        await s.render()

    await user.open("/test-count-fail")
    with caplog.at_level(logging.ERROR):
        # Failure returns None so the delete dialog can render "count
        # unavailable" instead of lying with a confident "0".
        assert sidebar_ref[0]._count_conversations_for_project("p1") is None
    assert "Failed to count conversations" in caplog.text
    caplog.clear()


@pytest.mark.asyncio
async def test_delete_dialog_renders_unknown_count_on_read_failure(
    user: User, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.list_conversations = Mock(side_effect=OSError("io"))
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    @ui.page("/test-delete-unknown-count")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()
        await s._open_delete_project_dialog("p1")

    await user.open("/test-delete-unknown-count")
    await user.should_see("Could not determine how many conversations")
    caplog.clear()


@pytest.mark.asyncio
async def test_open_new_project_dialog_builds_form(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)

    @ui.page("/test-new-dialog-open")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()
        s._open_new_project_dialog()

    await user.open("/test-new-dialog-open")
    await user.should_see("New Project")
    await user.should_see("Create")


@pytest.mark.asyncio
async def test_open_edit_project_dialog_builds_form(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    @ui.page("/test-edit-dialog-open")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()
        await s._open_edit_project_dialog("p1")

    await user.open("/test-edit-dialog-open")
    await user.should_see("Edit Project")


@pytest.mark.asyncio
async def test_open_delete_project_dialog_builds_form(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="hi")], project_id="p1")
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    @ui.page("/test-delete-dialog-open")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()
        await s._open_delete_project_dialog("p1")

    await user.open("/test-delete-dialog-open")
    await user.should_see("Delete 'Alpha'?")
    await user.should_see("This will also delete 1 conversation.")


@pytest.mark.asyncio
async def test_open_delete_project_dialog_pluralizes(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="a")], project_id="p1")
    store.save_sync("c2", [Message(role="user", content="b")], project_id="p1")
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="")
    )

    @ui.page("/test-delete-dialog-plural")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        await s.render()
        await s._open_delete_project_dialog("p1")

    await user.open("/test-delete-dialog-plural")
    await user.should_see("This will also delete 2 conversations.")


@pytest.mark.asyncio
async def test_delete_project_dialog_cancel_button_leaves_state_untouched(
    user: User, tmp_path: Path
) -> None:
    """Locks item 5: clicking Cancel on the delete confirmation dialog
    must not invoke `_delete_project` — the project record, conversations,
    and active state must all survive. Pre-F4 only the Delete-button path
    was covered, so a regression swapping the Cancel handler to the
    confirm path would pass CI silently.
    """
    session = Session(provider=FakeProvider())
    session.project_id = "p1"
    session.project_instructions = "keep"
    store = make_store(tmp_path)
    store.save_sync("c1", [Message(role="user", content="a")], project_id="p1")
    project_store = make_project_store(tmp_path)
    project_store.save_sync(
        ProjectRecord(id="p1", name="Alpha", folder="/tmp/a", instructions="keep")
    )

    sidebar_ref: list[Sidebar] = []

    @ui.page("/test-delete-dialog-cancel")
    async def page() -> None:
        s = Sidebar(session, store, lambda *_: None, project_store)
        s._active_project_id = "p1"
        sidebar_ref.append(s)
        await s.render()
        await s._open_delete_project_dialog("p1")

    await user.open("/test-delete-dialog-cancel")
    await user.should_see("Delete 'Alpha'?")
    user.find("Cancel").click()
    # Dialog close is in-flight; give the event loop a tick.
    await user.should_see("Alpha")  # project row still visible post-cancel

    assert project_store.load("p1") is not None
    assert {s.id for s in store.list_conversations()} == {"c1"}
    assert sidebar_ref[0]._active_project_id == "p1"
    assert session.project_id == "p1"
    assert session.project_instructions == "keep"


