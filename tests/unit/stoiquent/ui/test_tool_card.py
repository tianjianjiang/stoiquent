from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.models import ToolCall
from stoiquent.ui.tool_card import render_tool_call, render_tool_result


@pytest.mark.asyncio
async def test_should_render_tool_call_card(user: User) -> None:
    tc = ToolCall(id="tc1", name="greet", arguments={"name": "Alice"})

    @ui.page("/test-tc")
    async def page() -> None:
        render_tool_call(tc)

    await user.open("/test-tc")
    await user.should_see("greet")
    await user.should_see("Arguments")


@pytest.mark.asyncio
async def test_should_render_tool_call_card_without_arguments(user: User) -> None:
    tc = ToolCall(id="tc2", name="ping", arguments={})

    @ui.page("/test-tc-no-args")
    async def page() -> None:
        render_tool_call(tc)

    await user.open("/test-tc-no-args")
    await user.should_see("ping")


@pytest.mark.asyncio
async def test_should_render_tool_result_card(user: User) -> None:
    @ui.page("/test-tr")
    async def page() -> None:
        render_tool_result("tc1", "Hello, Alice!")

    await user.open("/test-tr")
    await user.should_see("Result")
    await user.should_see("Output")


@pytest.mark.asyncio
async def test_should_render_tool_result_card_empty_content(user: User) -> None:
    @ui.page("/test-tr-empty")
    async def page() -> None:
        render_tool_result("tc1", "")

    await user.open("/test-tr-empty")
    await user.should_see("Result")
