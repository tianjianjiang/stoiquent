"""E2E tests for UI interaction using NiceGUI User fixture.

Uses the User fixture (NiceGUI's recommended approach) for fast,
reliable interactive testing without a browser. Covers: sending messages,
session switching, skills toggling, tab navigation, provider dropdown.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.models import (
    AppConfig,
    Message,
    PersistenceConfig,
    ProviderConfig,
    StreamChunk,
)
from stoiquent.persistence import ConversationStore
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta
from stoiquent.ui import layout
from tests.conftest import FakeProvider


def _make_skill(name: str, description: str, active: bool = False) -> Skill:
    return Skill(
        meta=SkillMeta(name=name, description=description),
        path=Path("/fake"),
        instructions="",
        active=active,
        source="config",
    )


def _make_store(tmp_path: Path) -> ConversationStore:
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    store.ensure_dirs()
    return store


# --- Send message ---


async def test_send_message_shows_response(user: User) -> None:
    chunks = [
        StreamChunk(content_delta="Hello from the agent!"),
        StreamChunk(finish_reason="stop"),
    ]
    session = Session(provider=FakeProvider(chunks=chunks))

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    await user.open("/")
    user.find(marker="chat-input").type("Hi there")
    user.find(marker="send-btn").click()
    await user.should_see("Hello from the agent!")


# --- Tab navigation ---


async def test_sidebar_tabs_navigation(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

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


# --- Skills toggle ---


async def test_skills_tab_shows_toggles(user: User) -> None:
    catalog = SkillCatalog({
        "greet": _make_skill("greet", "Greeting skill", active=True),
        "search": _make_skill("search", "Search skill", active=False),
    })
    session = Session(provider=FakeProvider(), catalog=catalog)

    @ui.page("/")
    async def page() -> None:
        await layout.render(session)

    await user.open("/")
    user.find(marker="skills-tab").click()
    await user.should_see("greet")
    await user.should_see("Greeting skill")
    await user.should_see("search")
    await user.should_see("Search skill")


# --- Session list + load ---


async def test_session_list_and_load(user: User, tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("s1", [Message(role="user", content="First chat")])
    store.save_sync("target", [
        Message(role="user", content="Loaded question"),
        Message(role="assistant", content="Loaded answer"),
    ])

    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, store)

    await user.open("/")
    await user.should_see("First chat")
    await user.should_see("Loaded question")


# --- New Chat triggers on_session_switch ---


async def test_new_chat_resets_session(user: User, tmp_path: Path) -> None:
    """Cover layout.py lines 29-31: on_session_switch closure via New Chat."""
    store = _make_store(tmp_path)
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Old message")]

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, store)

    await user.open("/")
    user.find(marker="new-chat-btn").click()
    # Yield to event loop so async _new_session handler completes
    await asyncio.sleep(0.1)
    assert session.messages == []


# --- Provider dropdown ---


async def test_provider_change_clears_messages(user: User) -> None:
    """Cover layout.py lines 34-40: on_provider_change closure."""
    config = AppConfig(
        default_provider="local-qwen",
        providers={
            "local-qwen": ProviderConfig(
                base_url="http://localhost:11434/v1", model="qwen3:32b"
            ),
            "cloud-gpt": ProviderConfig(
                base_url="https://api.openai.com/v1", model="gpt-4"
            ),
        },
    )
    session = Session(provider=FakeProvider())
    session.messages = [Message(role="user", content="Before switch")]

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, config=config)

    await user.open("/")
    # Trigger provider change by setting value on the select element
    select_element = next(iter(user.find(marker="provider-select").elements))
    select_element.set_value("cloud-gpt")
    await asyncio.sleep(0.1)
    assert session.messages == []


async def test_provider_dropdown_renders_with_config(user: User) -> None:
    config = AppConfig(
        default_provider="local-qwen",
        providers={
            "local-qwen": ProviderConfig(
                base_url="http://localhost:11434/v1", model="qwen3:32b"
            ),
            "cloud-gpt": ProviderConfig(
                base_url="https://api.openai.com/v1", model="gpt-4"
            ),
        },
    )
    session = Session(provider=FakeProvider())

    @ui.page("/")
    async def page() -> None:
        await layout.render(session, config=config)

    await user.open("/")
    await user.should_see("Stoiquent")
    await user.should_see("local-qwen")
    await user.should_see("Local LLM Agent")
