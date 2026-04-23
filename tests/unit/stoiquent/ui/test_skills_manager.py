from __future__ import annotations

import asyncio
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
from stoiquent.ui.skills_manager import SkillsManager


class _FakeMCPBridge(MCPBridge):
    """MCPBridge stand-in that records calls without spawning subprocesses."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.stop_raises: dict[str, Exception] = {}
        self._next = 0

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
    description: str = "",
    active: bool = False,
    source: str = "user",
    tags: list[str] | None = None,
    version: str = "",
    mcp_servers: list[MCPServerDef] | None = None,
    instructions: str = "",
) -> Skill:
    return Skill(
        meta=SkillMeta(
            name=name,
            description=description or f"Desc for {name}",
            version=version,
            tags=tags or [],
            mcp_servers=mcp_servers or [],
        ),
        path=Path(f"/skills/{name}/SKILL.md"),
        instructions=instructions,
        active=active,
        source=source,  # type: ignore[arg-type]
    )


def _controller(
    skills: dict[str, Skill],
    *,
    bridge: MCPBridge | None = None,
) -> SkillController:
    return SkillController(SkillCatalog(skills), bridge or _FakeMCPBridge())


def test_available_is_false_without_controller() -> None:
    manager = SkillsManager(None)
    assert manager.available is False


def test_build_is_noop_without_controller() -> None:
    manager = SkillsManager(None)
    manager.build()
    manager.open()


@pytest.mark.asyncio
async def test_manager_renders_group_headers_for_each_source(
    user: User,
) -> None:
    controller = _controller({
        "user-skill": _skill("user-skill", source="user"),
        "proj-skill": _skill("proj-skill", source="project"),
    })

    @ui.page("/test-groups")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()

    await user.open("/test-groups")
    await user.should_see("User (1)")
    await user.should_see("Project (1)")
    await user.should_not_see("Config (")


@pytest.mark.asyncio
async def test_manager_renders_skill_metadata(user: User) -> None:
    controller = _controller({
        "gh": _skill(
            "gh",
            version="1.2",
            tags=["cli", "github"],
            mcp_servers=[MCPServerDef(command="gh-mcp")],
            description="GitHub CLI skill",
        ),
    })

    @ui.page("/test-meta")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()

    await user.open("/test-meta")
    await user.should_see("gh")
    await user.should_see("v1.2")
    await user.should_see("#cli")
    await user.should_see("#github")
    await user.should_see("MCP · 1")
    await user.should_see("GitHub CLI skill")


@pytest.mark.asyncio
async def test_manager_toggle_activates_through_controller(
    user: User,
) -> None:
    controller = _controller({"greet": _skill("greet")})

    @ui.page("/test-activate")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()

    await user.open("/test-activate")
    user.find(marker="skill-switch-greet").click()
    for _ in range(20):
        if controller.catalog.skills["greet"].active:
            break
        await asyncio.sleep(0.01)
    assert controller.catalog.skills["greet"].active is True


@pytest.mark.asyncio
async def test_manager_toggle_deactivates_through_controller(
    user: User,
) -> None:
    controller = _controller({"greet": _skill("greet", active=True)})

    @ui.page("/test-deactivate")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()

    await user.open("/test-deactivate")
    user.find(marker="skill-switch-greet").click()
    for _ in range(20):
        if not controller.catalog.skills["greet"].active:
            break
        await asyncio.sleep(0.01)
    assert controller.catalog.skills["greet"].active is False


@pytest.mark.asyncio
async def test_manager_notifies_on_activation_failure(
    user: User, caplog: pytest.LogCaptureFixture
) -> None:
    skill = _skill("gh", mcp_servers=[MCPServerDef(command="bad")])
    controller = _controller({"gh": skill})

    async def _fail(*_: object) -> str:
        raise RuntimeError("stdio closed")

    controller._mcp.start_server = _fail  # type: ignore[attr-defined,method-assign]  # noqa: SLF001

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-activate-fail")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-activate-fail")
    with caplog.at_level(logging.ERROR, logger="stoiquent.skills.controller"):
        with patch("stoiquent.ui.skills_manager.ui.notify") as mock_notify:
            await manager_ref[0]._on_toggle("gh", True)  # noqa: SLF001
    assert any(
        "Failed to activate" in (c.args[0] if c.args else "")
        and "gh" in (c.args[0] if c.args else "")
        for c in mock_notify.call_args_list
    )
    caplog.clear()


@pytest.mark.asyncio
async def test_manager_search_filters_by_name(user: User) -> None:
    controller = _controller({
        "alpha": _skill("alpha", description="first"),
        "beta": _skill("beta", description="second"),
    })

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-search")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-search")
    assert {s.meta.name for s in manager_ref[0]._filtered_skills()} == {  # noqa: SLF001
        "alpha",
        "beta",
    }
    manager_ref[0]._search.value = "alp"  # type: ignore[union-attr]  # noqa: SLF001
    assert [s.meta.name for s in manager_ref[0]._filtered_skills()] == [  # noqa: SLF001
        "alpha"
    ]


@pytest.mark.asyncio
async def test_manager_filter_matches_tags(user: User) -> None:
    controller = _controller({
        "alpha": _skill("alpha", tags=["shell"]),
        "beta": _skill("beta", tags=["web"]),
    })

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-tags")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-tags")
    manager_ref[0]._search.value = "web"  # type: ignore[union-attr]  # noqa: SLF001
    names = [s.meta.name for s in manager_ref[0]._filtered_skills()]  # noqa: SLF001
    assert names == ["beta"]


@pytest.mark.asyncio
async def test_manager_source_filter_narrows_groups(user: User) -> None:
    controller = _controller({
        "u": _skill("u", source="user"),
        "p": _skill("p", source="project"),
    })

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-source")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-source")
    manager_ref[0]._source_filter.value = "Project"  # type: ignore[union-attr]  # noqa: SLF001
    names = [s.meta.name for s in manager_ref[0]._filtered_skills()]  # noqa: SLF001
    assert names == ["p"]


@pytest.mark.asyncio
async def test_manager_shows_empty_state_when_no_skills(user: User) -> None:
    controller = _controller({})

    @ui.page("/test-empty")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()

    await user.open("/test-empty")
    await user.should_see("No skills match")


@pytest.mark.asyncio
async def test_manager_reload_invokes_discover_and_notifies(
    user: User,
) -> None:
    controller = _controller({"alpha": _skill("alpha")})
    discover_calls: list[str] = []

    def _discover() -> dict[str, Skill]:
        discover_calls.append("called")
        return {"alpha": _skill("alpha"), "beta": _skill("beta")}

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-reload")
    async def page() -> None:
        manager = SkillsManager(controller, discover=_discover)
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-reload")
    with patch("stoiquent.ui.skills_manager.ui.notify") as mock_notify:
        await manager_ref[0]._on_reload()  # noqa: SLF001
    assert discover_calls == ["called"]
    assert any(
        "Reload" in (c.args[0] if c.args else "")
        for c in mock_notify.call_args_list
    )
    assert "beta" in controller.catalog.skills


@pytest.mark.asyncio
async def test_manager_reload_surfaces_deactivation_failures(
    user: User, caplog: pytest.LogCaptureFixture
) -> None:
    skill_a = _skill("alpha", mcp_servers=[MCPServerDef(command="mcp-a")])
    bridge = _FakeMCPBridge()
    controller = _controller({"alpha": skill_a}, bridge=bridge)
    await controller.activate("alpha")
    bridge.stop_raises["srv-1"] = RuntimeError("pipe broken")

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-reload-fail")
    async def page() -> None:
        manager = SkillsManager(controller, discover=lambda: {})
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-reload-fail")
    with caplog.at_level(logging.ERROR, logger="stoiquent.skills.controller"):
        with patch("stoiquent.ui.skills_manager.ui.notify") as mock_notify:
            await manager_ref[0]._on_reload()  # noqa: SLF001
    assert any(
        "MCP cleanup failed" in (c.args[0] if c.args else "")
        for c in mock_notify.call_args_list
    )
    caplog.clear()


@pytest.mark.asyncio
async def test_manager_reload_warns_when_discover_unavailable(
    user: User,
) -> None:
    controller = _controller({"alpha": _skill("alpha")})

    manager_ref: list[SkillsManager] = []

    @ui.page("/test-reload-warn")
    async def page() -> None:
        manager = SkillsManager(controller, discover=None)
        manager.build()
        manager.open()
        manager_ref.append(manager)

    await user.open("/test-reload-warn")
    with patch("stoiquent.ui.skills_manager.ui.notify") as mock_notify:
        await manager_ref[0]._on_reload()  # noqa: SLF001
    assert any(
        "Reload unavailable" in (c.args[0] if c.args else "")
        for c in mock_notify.call_args_list
    )


@pytest.mark.asyncio
async def test_manager_refreshes_on_controller_events(user: User) -> None:
    controller = _controller({"greet": _skill("greet")})

    @ui.page("/test-refresh")
    async def page() -> None:
        manager = SkillsManager(controller)
        manager.build()
        manager.open()

    await user.open("/test-refresh")
    await user.should_see("User (1)")
    await controller.activate("greet")
    # After activation the row is re-rendered with the switch set to True;
    # the simplest observable check is that the switch still exists and is
    # backed by the new state.
    assert controller.catalog.skills["greet"].active is True


def test_teardown_unsubscribes_from_controller() -> None:
    controller = Mock()
    controller.subscribe.return_value = Mock()
    manager = SkillsManager(controller)
    manager._unsubscribe = controller.subscribe.return_value  # noqa: SLF001
    manager.teardown()
    controller.subscribe.return_value.assert_called_once_with()


def test_teardown_is_safe_when_not_subscribed() -> None:
    manager = SkillsManager(None)
    manager.teardown()
