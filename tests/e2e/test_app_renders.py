from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from nicegui import ui
from nicegui.testing import Screen

from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk
from stoiquent.ui import layout


@dataclass
class FakeProvider:
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content_delta="Hello from fake!")
        yield StreamChunk(finish_reason="stop")


@pytest.fixture
def fake_session() -> Session:
    return Session(provider=FakeProvider())


def test_should_render_app_header(screen: Screen, fake_session: Session) -> None:
    @ui.page("/")
    async def page() -> None:
        layout.render(fake_session)

    screen.open("/")
    screen.should_contain("Stoiquent")


def test_should_render_sidebar(screen: Screen, fake_session: Session) -> None:
    @ui.page("/")
    async def page() -> None:
        layout.render(fake_session)

    screen.open("/")
    screen.should_contain("Sessions")


def test_should_render_chat_input(screen: Screen, fake_session: Session) -> None:
    @ui.page("/")
    async def page() -> None:
        layout.render(fake_session)

    screen.open("/")
    screen.should_contain("Send")
