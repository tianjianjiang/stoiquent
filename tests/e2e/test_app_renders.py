from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import Screen

from stoiquent.agent.session import Session
from stoiquent.ui import layout
from tests.conftest import FakeProvider


def test_should_render_app_header(screen: Screen, fake_session: Session) -> None:
    @ui.page("/")
    async def page() -> None:
        await layout.render(fake_session)

    screen.open("/")
    screen.should_contain("Stoiquent")


def test_should_render_sidebar(screen: Screen, fake_session: Session) -> None:
    @ui.page("/")
    async def page() -> None:
        await layout.render(fake_session)

    screen.open("/")
    screen.should_contain("Sessions")


def test_should_render_chat_input(screen: Screen, fake_session: Session) -> None:
    @ui.page("/")
    async def page() -> None:
        await layout.render(fake_session)

    screen.open("/")
    screen.should_contain("Send")
