"""E2E tests verifying the app renders correctly.

Uses the User fixture (NiceGUI's recommended approach).
"""

from __future__ import annotations

from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.ui import layout
from tests.conftest import FakeProvider


async def test_should_render_app_header(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    await user.open("/")
    await user.should_see("Stoiquent")


async def test_should_render_sidebar(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    await user.open("/")
    await user.should_see("Sessions")


async def test_should_render_chat_input(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    await user.open("/")
    await user.should_see("Send")
