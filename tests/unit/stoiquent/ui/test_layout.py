from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from nicegui.testing import User

from pathlib import Path

from stoiquent.agent.session import Session
from stoiquent.models import Message, PersistenceConfig
from stoiquent.projects import ProjectRecord, ProjectStore
from stoiquent.ui import layout
from stoiquent.ui.layout import (
    _apply_session_switch,
    _load_project_instructions,
    _switch_provider,
)
from stoiquent.ui.sidebar import SessionSwitch
from tests.conftest import FakeProvider, make_project_store, two_provider_config


@pytest.mark.asyncio
async def test_should_render_layout_with_header_and_sidebar(
    user: User, tmp_path: Path
) -> None:
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/test-layout")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/test-layout")
    await user.should_see("Stoiquent")
    await user.should_see("Sessions")
    await user.should_see("Skills")
    await user.should_see("New Chat")


@pytest.mark.asyncio
async def test_should_render_local_llm_label(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/test-label")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/test-label")
    await user.should_see("Local LLM Agent")


@pytest.mark.asyncio
async def test_layout_mounts_dark_mode_toggle(user: User, tmp_path: Path) -> None:
    """Header must include the DarkModeToggle so users can flip themes."""
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/test-dark-toggle")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/test-dark-toggle")
    toggles = list(user.find(marker="dark-mode-toggle").elements)
    assert len(toggles) == 1, f"expected exactly one dark-mode toggle, got {toggles}"


@pytest.mark.asyncio
async def test_should_render_provider_dropdown(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    config = two_provider_config(second="cloud-gpt")
    project_store = make_project_store(tmp_path)

    @ui.page("/test-dropdown")
    async def page() -> None:
        await layout.render(session, config=config, project_store=project_store)

    await user.open("/test-dropdown")
    await user.should_see("Stoiquent")
    await user.should_see("local-qwen")


@pytest.mark.asyncio
async def test_session_switch_updates_messages(user: User) -> None:
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Old")]

    from stoiquent.ui.chat import ChatPanel

    chat = ChatPanel(session)

    def on_switch(new_id: str, new_msgs: list[Message]) -> None:
        session.id = new_id
        session.messages = new_msgs
        chat.reload_messages()

    on_switch("new123", [Message(role="user", content="Reloaded")])

    assert session.id == "new123"
    assert len(session.messages) == 1
    assert session.messages[0].content == "Reloaded"


def test_switch_provider_changes_session_provider() -> None:
    session = Session(provider=FakeProvider())
    config = two_provider_config()

    original = session.provider
    result = _switch_provider(session, config, "other")
    assert result is True
    assert session.provider is not original


async def test_switch_provider_with_closeable_provider() -> None:
    """Verify old provider's close() is scheduled when switching."""
    close_mock = AsyncMock()
    provider = FakeProvider()
    provider.close = close_mock  # type: ignore[attr-defined]

    session = Session(provider=provider)
    config = two_provider_config()

    _switch_provider(session, config, "other")
    # Yield to event loop so the create_task(provider.close()) completes
    await asyncio.sleep(0)

    assert session.provider is not provider
    close_mock.assert_awaited_once()


def test_switch_provider_returns_false_for_none_config() -> None:
    session = Session(provider=FakeProvider())
    assert _switch_provider(session, None, "anything") is False


def test_switch_provider_returns_false_for_unknown_name() -> None:
    session = Session(provider=FakeProvider())
    config = two_provider_config()

    original = session.provider
    result = _switch_provider(session, config, "nonexistent")
    assert result is False
    assert session.provider is original


def test_switch_provider_logs_warning_when_no_event_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cover lines 87-88: RuntimeError branch when no event loop is running."""
    provider = FakeProvider()
    provider.close = AsyncMock()  # type: ignore[attr-defined]

    session = Session(provider=provider)
    config = two_provider_config()

    with caplog.at_level(logging.WARNING):
        result = _switch_provider(session, config, "other")

    assert result is True
    assert "No event loop to close old provider" in caplog.text


async def test_switch_provider_logs_close_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cover line 81: _log_close_error callback when provider.close() raises."""
    provider = FakeProvider()
    provider.close = AsyncMock(side_effect=RuntimeError("close failed"))  # type: ignore[attr-defined]

    session = Session(provider=provider)
    config = two_provider_config()

    with caplog.at_level(logging.WARNING):
        _switch_provider(session, config, "other")
        # Two yields needed: first runs the task (which raises), second fires
        # the done-callback that logs the warning.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert "Failed to close old provider" in caplog.text


# --- _load_project_instructions ---


def test_load_project_instructions_returns_empty_when_store_is_none() -> None:
    assert _load_project_instructions(None, "proj1") == ""


def test_load_project_instructions_returns_empty_when_project_id_is_none(
    tmp_path: Path,
) -> None:
    store = ProjectStore(PersistenceConfig(data_dir=str(tmp_path)))
    store.ensure_dirs()
    assert _load_project_instructions(store, None) == ""


def test_load_project_instructions_returns_empty_when_project_missing(
    tmp_path: Path,
) -> None:
    store = ProjectStore(PersistenceConfig(data_dir=str(tmp_path)))
    store.ensure_dirs()
    assert _load_project_instructions(store, "nonexistent") == ""


def test_load_project_instructions_returns_record_instructions(
    tmp_path: Path,
) -> None:
    store = ProjectStore(PersistenceConfig(data_dir=str(tmp_path)))
    store.ensure_dirs()
    store.save_sync(
        ProjectRecord(
            id="proj1",
            name="My Project",
            folder=str(tmp_path),
            instructions="Use formal tone.",
        )
    )
    assert _load_project_instructions(store, "proj1") == "Use formal tone."


def test_load_project_instructions_swallows_load_exception(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any unexpected store exception must not block a session switch, and
    must not fire a toast — contract violations are bug-class, not
    data-damage; toasting them on every session switch after a bug would
    drown real signal. Symmetric with the ProjectLoadError test below
    which DOES toast."""
    store = ProjectStore(PersistenceConfig(data_dir=str(tmp_path)))
    store.ensure_dirs()

    def _raise(_project_id: str) -> None:
        raise RuntimeError("simulated store failure")

    monkeypatch.setattr(store, "load", _raise)
    mock_notify = Mock()
    monkeypatch.setattr("stoiquent.ui.layout.ui.notify", mock_notify)

    with caplog.at_level(logging.ERROR, logger="stoiquent.ui.layout"):
        result = _load_project_instructions(store, "proj1")

    assert result == ""
    assert any(
        "Unexpected failure loading project instructions for proj1" in r.message
        for r in caplog.records
    )
    mock_notify.assert_not_called()


def test_load_project_instructions_returns_empty_on_damaged_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tri-state load contract: ProjectLoadError is 'damaged' — logged at
    WARNING and surfaced via ui.notify, not buried at ERROR as
    'unexpected failure'."""
    store = ProjectStore(PersistenceConfig(data_dir=str(tmp_path)))
    store.ensure_dirs()
    (tmp_path / "projects" / "proj1.json").write_text("{corrupt", encoding="utf-8")

    mock_notify = Mock()
    monkeypatch.setattr("stoiquent.ui.layout.ui.notify", mock_notify)

    with caplog.at_level(logging.WARNING, logger="stoiquent.ui.layout"):
        result = _load_project_instructions(store, "proj1")

    assert result == ""
    warning_records = [
        r
        for r in caplog.records
        if r.levelname == "WARNING"
        and r.name == "stoiquent.ui.layout"
        and "proj1" in r.message
    ]
    assert warning_records, "expected a WARNING log from layout about proj1"
    assert not any(
        r.levelname == "ERROR" and r.name == "stoiquent.ui.layout"
        for r in caplog.records
    )
    mock_notify.assert_called_once_with(
        "Project instructions unavailable — project file is damaged",
        type="warning",
    )


# --- _apply_session_switch ---


def test_apply_session_switch_clears_stale_project_instructions(
    tmp_path: Path,
) -> None:
    """Switching to a session with project_id=None must clear stale instructions."""
    session = Session(provider=FakeProvider())
    session.project_id = "projA"
    session.project_instructions = "A-only guidance"

    _apply_session_switch(
        session,
        None,
        SessionSwitch(
            session_id="new_id",
            messages=[Message(role="user", content="fresh")],
            project_id=None,
        ),
    )

    assert session.project_id is None
    assert session.project_instructions == ""
    assert session.id == "new_id"
    assert len(session.messages) == 1


def test_apply_session_switch_loads_new_project_instructions(
    tmp_path: Path,
) -> None:
    """Switching into a different project must replace instructions, not append."""
    store = ProjectStore(PersistenceConfig(data_dir=str(tmp_path)))
    store.ensure_dirs()
    store.save_sync(
        ProjectRecord(
            id="projB",
            name="Project B",
            folder=str(tmp_path),
            instructions="B-only guidance",
        )
    )

    session = Session(provider=FakeProvider())
    session.project_id = "projA"
    session.project_instructions = "A-only guidance"

    _apply_session_switch(
        session,
        store,
        SessionSwitch(session_id="sid", messages=[], project_id="projB"),
    )

    assert session.project_id == "projB"
    assert session.project_instructions == "B-only guidance"


@pytest.mark.asyncio
async def test_layout_registers_client_disconnect_teardown(
    user: User, tmp_path: Path
) -> None:
    """Regression guard: layout.render must register ``ui.context.client.
    on_disconnect(...)`` so SkillsManager and Sidebar release controller
    subscriptions when the browser disconnects. We verify by spying on
    ``Client.on_disconnect`` and asserting at least one handler was
    registered during page render."""
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    from nicegui.client import Client

    original = Client.on_disconnect
    captured: list[object] = []

    def _spy(self: Client, cb: object) -> None:
        captured.append(cb)
        original(self, cb)

    Client.on_disconnect = _spy  # type: ignore[method-assign,assignment]
    try:
        @ui.page("/test-teardown-registration")
        async def page() -> None:
            await layout.render(session, None, None, project_store=project_store)

        await user.open("/test-teardown-registration")
    finally:
        Client.on_disconnect = original  # type: ignore[method-assign]

    assert captured, "layout.render must register an on_disconnect handler"
    assert callable(captured[-1])
    captured[-1]()  # must be safe to invoke — teardowns are idempotent
