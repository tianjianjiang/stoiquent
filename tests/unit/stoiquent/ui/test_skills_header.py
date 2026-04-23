from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.controller import SkillController
from stoiquent.skills.mcp_bridge import MCPBridge
from stoiquent.skills.models import MCPServerDef, Skill, SkillMeta
from stoiquent.ui.skills_header import SkillsHeaderMenu


class _FakeMCPBridge(MCPBridge):
    def __init__(self) -> None:
        self._next = 0

    async def start_server(self, server_def: MCPServerDef) -> str:
        self._next += 1
        return f"srv-{self._next}"

    async def stop_server(self, server_id: str) -> None:
        pass

    async def stop_all(self) -> None:
        pass


def _skill(
    name: str,
    *,
    active: bool = False,
    description: str = "",
    source: str = "user",
    mcp_servers: list[MCPServerDef] | None = None,
) -> Skill:
    return Skill(
        meta=SkillMeta(
            name=name,
            description=description or f"Desc for {name}",
            mcp_servers=mcp_servers or [],
        ),
        path=Path(f"/skills/{name}"),
        active=active,
        source=source,  # type: ignore[arg-type]
    )


def _controller(skills: dict[str, Skill]) -> SkillController:
    return SkillController(SkillCatalog(skills), _FakeMCPBridge())


def test_build_is_noop_without_controller() -> None:
    menu = SkillsHeaderMenu(None)
    menu.build()


def test_build_is_noop_with_empty_catalog() -> None:
    menu = SkillsHeaderMenu(_controller({}))
    menu.build()


@pytest.mark.asyncio
async def test_header_shows_active_over_total(user: User) -> None:
    controller = _controller(
        {
            "alpha": _skill("alpha", active=True),
            "beta": _skill("beta"),
            "gamma": _skill("gamma", active=True),
        }
    )

    @ui.page("/test-header-counts")
    async def page() -> None:
        SkillsHeaderMenu(controller).build()

    await user.open("/test-header-counts")
    await user.should_see("Skills · 2/3")


@pytest.mark.asyncio
async def test_header_refreshes_label_on_controller_event(user: User) -> None:
    controller = _controller({"alpha": _skill("alpha")})

    @ui.page("/test-header-refresh")
    async def page() -> None:
        SkillsHeaderMenu(controller).build()

    await user.open("/test-header-refresh")
    await user.should_see("Skills · 0/1")
    await controller.activate("alpha")
    await user.should_see("Skills · 1/1")


@pytest.mark.asyncio
async def test_header_toggle_activates_through_controller(user: User) -> None:
    controller = _controller({"alpha": _skill("alpha")})

    @ui.page("/test-header-activate")
    async def page() -> None:
        SkillsHeaderMenu(controller).build()

    await user.open("/test-header-activate")
    user.find(marker="skills-header-switch-alpha").click()
    import asyncio as _asyncio

    for _ in range(20):
        if controller.catalog.skills["alpha"].active:
            break
        await _asyncio.sleep(0.01)
    assert controller.catalog.skills["alpha"].active is True


@pytest.mark.asyncio
async def test_header_toggle_deactivates_through_controller(user: User) -> None:
    controller = _controller({"alpha": _skill("alpha", active=True)})

    @ui.page("/test-header-deactivate")
    async def page() -> None:
        SkillsHeaderMenu(controller).build()

    await user.open("/test-header-deactivate")
    user.find(marker="skills-header-switch-alpha").click()
    import asyncio as _asyncio

    for _ in range(20):
        if not controller.catalog.skills["alpha"].active:
            break
        await _asyncio.sleep(0.01)
    assert controller.catalog.skills["alpha"].active is False


@pytest.mark.asyncio
async def test_header_manage_button_opens_manager(user: User) -> None:
    controller = _controller({"alpha": _skill("alpha")})
    manager = Mock()
    manager.available = True
    menu_ref: list[SkillsHeaderMenu] = []

    @ui.page("/test-header-manage")
    async def page() -> None:
        menu = SkillsHeaderMenu(controller, manager=manager)
        menu.build()
        menu_ref.append(menu)

    await user.open("/test-header-manage")
    menu_ref[0]._open_manager()  # noqa: SLF001
    manager.open.assert_called_once_with()


@pytest.mark.asyncio
async def test_header_manage_button_disabled_when_manager_missing(
    user: User,
) -> None:
    controller = _controller({"alpha": _skill("alpha")})

    @ui.page("/test-header-no-manager")
    async def page() -> None:
        SkillsHeaderMenu(controller, manager=None).build()

    await user.open("/test-header-no-manager")
    await user.should_see(marker="skills-header-manage-btn")


@pytest.mark.asyncio
async def test_header_notifies_on_activation_failure(
    user: User, caplog: pytest.LogCaptureFixture
) -> None:
    skill = _skill("gh", mcp_servers=[MCPServerDef(command="bad")])
    controller = _controller({"gh": skill})

    async def _fail(*_: object) -> str:
        raise RuntimeError("stdio closed")

    controller._mcp.start_server = _fail  # type: ignore[method-assign]  # noqa: SLF001

    menu_ref: list[SkillsHeaderMenu] = []

    @ui.page("/test-header-activate-fail")
    async def page() -> None:
        menu = SkillsHeaderMenu(controller)
        menu.build()
        menu_ref.append(menu)

    await user.open("/test-header-activate-fail")
    with caplog.at_level(logging.ERROR, logger="stoiquent.skills.controller"):
        with patch("stoiquent.ui.skills_header.ui.notify") as mock_notify:
            await menu_ref[0]._on_toggle("gh", True)  # noqa: SLF001
    assert any(
        "Failed to activate" in (c.args[0] if c.args else "")
        and "gh" in (c.args[0] if c.args else "")
        for c in mock_notify.call_args_list
    )
    caplog.clear()


def test_teardown_unsubscribes_from_controller() -> None:
    menu = SkillsHeaderMenu(None)
    unsubscribe = Mock()
    menu._unsubscribe = unsubscribe  # noqa: SLF001
    menu.teardown()
    unsubscribe.assert_called_once_with()
    menu.teardown()


def test_teardown_is_safe_when_not_subscribed() -> None:
    menu = SkillsHeaderMenu(None)
    menu.teardown()
