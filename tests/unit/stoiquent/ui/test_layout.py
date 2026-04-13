from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import Message, ProviderConfig, StreamChunk
from stoiquent.ui import layout


@dataclass
class FakeProvider:
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(finish_reason="stop")


@pytest.mark.asyncio
async def test_should_render_layout_with_header_and_sidebar(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/test-layout")
    async def page() -> None:
        layout.render(session)

    await user.open("/test-layout")
    await user.should_see("Stoiquent")
    await user.should_see("Sessions")
