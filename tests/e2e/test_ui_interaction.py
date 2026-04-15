"""E2E tests for UI interaction using NiceGUI Screen (Selenium).

Tests actual user interactions: typing messages, clicking buttons,
verifying responses appear in the browser.
"""

from __future__ import annotations

from nicegui import ui
from nicegui.testing import Screen

from stoiquent.agent.session import Session
from stoiquent.models import StreamChunk
from stoiquent.ui import layout
from tests.conftest import FakeProvider


def test_send_message_shows_response(screen: Screen) -> None:
    chunks = [
        StreamChunk(content_delta="Hello from the agent!"),
        StreamChunk(finish_reason="stop"),
    ]
    provider = FakeProvider(chunks=chunks)
    session = Session(provider=provider)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    screen.open("/")
    screen.should_contain("Send")

    # Find input by CSS and type
    input_el = screen.find_by_css("input")
    input_el.send_keys("Hi there")

    screen.click("Send")
    screen.wait_for("Hello from the agent!")
    screen.should_contain("Hello from the agent!")


def test_sidebar_shows_sessions_and_skills_tabs(screen: Screen) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    screen.open("/")
    screen.should_contain("Sessions")
    screen.should_contain("Skills")
    screen.should_contain("New Chat")


def test_header_shows_app_name_and_label(screen: Screen) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    screen.open("/")
    screen.should_contain("Stoiquent")
    screen.should_contain("Local LLM Agent")
