"""E2E tests verifying the app renders correctly.

Uses the User fixture (NiceGUI's recommended approach).
"""

from __future__ import annotations

from pathlib import Path

from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.ui import layout
from tests.conftest import FakeProvider, make_project_store


async def test_should_render_app_header(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/")
    await user.should_see("Stoiquent")


async def test_should_render_sidebar(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/")
    await user.should_see("Sessions")


async def test_should_render_chat_input(user: User, tmp_path: Path) -> None:
    session = Session(provider=FakeProvider())
    project_store = make_project_store(tmp_path)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, project_store=project_store)

    await user.open("/")
    await user.should_see("Send")
