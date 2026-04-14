from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.agent.session import Session
from stoiquent.ui import layout
from tests.conftest import FakeProvider


@pytest.mark.asyncio
async def test_should_render_layout_with_header_and_sidebar(user: User) -> None:
    session = Session(provider=FakeProvider())

    @ui.page("/test-layout")
    async def page() -> None:
        layout.render(session)

    await user.open("/test-layout")
    await user.should_see("Stoiquent")
    await user.should_see("Sessions")
