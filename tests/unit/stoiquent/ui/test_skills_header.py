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
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.stop_raises: dict[str, Exception] = {}

    async def start_server(self, server_def: MCPServerDef) -> str:
        self._next += 1
        sid = f"srv-{self._next}"
        self.started.append(sid)
        return sid

    async def stop_server(self, server_id: str) -> None:
        self.stopped.append(server_id)
        if server_id in self.stop_raises:
            raise self.stop_raises[server_id]

    async def stop_all(self) -> None:
        for sid in list(self.started):
            await self.stop_server(sid)


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
    """The previous version only asserted the button rendered — a
    regression that dropped the ``disable()`` call would silently ship a
    dead-but-clickable button. Capture the button element and assert its
    disabled state on the widget props."""
    controller = _controller({"alpha": _skill("alpha")})
    menu_ref: list[SkillsHeaderMenu] = []

    @ui.page("/test-header-no-manager")
    async def page() -> None:
        menu = SkillsHeaderMenu(controller, manager=None)
        menu.build()
        menu_ref.append(menu)

    await user.open("/test-header-no-manager")
    await user.should_see(marker="skills-header-manage-btn")
    manage_btn = user.find(marker="skills-header-manage-btn").elements.pop()
    assert getattr(manage_btn, "enabled", True) is False, (
        "manage button must be disabled when manager is absent"
    )


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


@pytest.mark.asyncio
async def test_header_toggle_renders_deactivation_cleanup_warnings(
    user: User, caplog: pytest.LogCaptureFixture
) -> None:
    """SkillsHeaderMenu must honor the same "render result.warnings"
    contract as SkillsManager — deactivate with cleanup errors returns
    success=True but populates warnings; the header quick-toggle must
    surface those to the user."""
    skill = _skill("leaky", mcp_servers=[MCPServerDef(command="x")])
    controller = _controller({"leaky": skill})
    await controller.activate("leaky")
    assert isinstance(controller._mcp, _FakeMCPBridge)  # noqa: SLF001
    controller._mcp.stop_raises["srv-1"] = RuntimeError("cleanup exploded")  # noqa: SLF001

    menu_ref: list[SkillsHeaderMenu] = []

    @ui.page("/test-header-deactivate-cleanup-warning")
    async def page() -> None:
        menu = SkillsHeaderMenu(controller)
        menu.build()
        menu_ref.append(menu)

    await user.open("/test-header-deactivate-cleanup-warning")
    with caplog.at_level(logging.ERROR, logger="stoiquent.skills.controller"):
        with patch("stoiquent.ui.skills_header.ui.notify") as mock_notify:
            await menu_ref[0]._on_toggle("leaky", False)  # noqa: SLF001
    warning_messages = [
        c.args[0] for c in mock_notify.call_args_list if c.args
    ]
    assert any(
        "leaky" in msg and "MCP cleanup failed" in msg
        for msg in warning_messages
    ), f"leak warning should surface to UI; got {warning_messages!r}"
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
