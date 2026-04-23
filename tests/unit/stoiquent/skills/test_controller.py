from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stoiquent.models import PersistenceConfig
from stoiquent.skills.active_store import ActiveSkillsStore
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.controller import ActivationResult, SkillController
from stoiquent.skills.models import MCPServerDef, Skill, SkillMeta


def _make_skill(
    name: str,
    *,
    active: bool = False,
    mcp_servers: list[MCPServerDef] | None = None,
) -> Skill:
    return Skill(
        meta=SkillMeta(
            name=name,
            description=f"Test skill {name}",
            mcp_servers=mcp_servers or [],
        ),
        path=Path(f"/skills/{name}"),
        instructions=f"Instructions for {name}",
        active=active,
    )


@dataclass
class FakeMCPBridge:
    """Records start/stop calls and returns deterministic server IDs.

    ``start_raises`` and ``stop_raises`` inject failures keyed by server
    command / id so tests can drive rollback and cleanup-error paths
    without real subprocess I/O.
    """

    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    start_raises: dict[str, Exception] = field(default_factory=dict)
    stop_raises: dict[str, Exception] = field(default_factory=dict)
    _next_id: int = 0

    async def start_server(self, server_def: MCPServerDef) -> str:
        if server_def.command in self.start_raises:
            raise self.start_raises[server_def.command]
        self._next_id += 1
        server_id = f"srv-{self._next_id}"
        self.started.append(server_id)
        return server_id

    async def stop_server(self, server_id: str) -> None:
        if server_id in self.stop_raises:
            self.stopped.append(server_id)
            raise self.stop_raises[server_id]
        self.stopped.append(server_id)


def _controller(
    skills: dict[str, Skill],
    *,
    tmp_path: Path | None = None,
) -> tuple[SkillController, FakeMCPBridge, SkillCatalog]:
    catalog = SkillCatalog(skills)
    bridge = FakeMCPBridge()
    store = (
        ActiveSkillsStore(PersistenceConfig(data_dir=str(tmp_path)))
        if tmp_path is not None
        else None
    )
    return SkillController(catalog, bridge, store), bridge, catalog  # type: ignore[arg-type]


async def test_activate_unknown_skill_returns_failure() -> None:
    controller, _, _ = _controller({})
    result = await controller.activate("nope")
    assert result == ActivationResult(False, "unknown-skill")


async def test_activate_marks_skill_active_without_mcp() -> None:
    controller, bridge, catalog = _controller({"hello": _make_skill("hello")})
    result = await controller.activate("hello")
    assert result.success and result.reason == "activated"
    assert catalog.skills["hello"].active is True
    assert bridge.started == []


async def test_activate_already_active_is_idempotent() -> None:
    controller, bridge, _ = _controller(
        {"hello": _make_skill("hello", active=True)}
    )
    result = await controller.activate("hello")
    assert result == ActivationResult(True, "already-active")
    assert bridge.started == []


async def test_activate_starts_declared_mcp_servers() -> None:
    skill = _make_skill(
        "gh",
        mcp_servers=[
            MCPServerDef(command="gh-mcp", args=["--flag"]),
            MCPServerDef(command="gh-auth"),
        ],
    )
    controller, bridge, _ = _controller({"gh": skill})
    await controller.activate("gh")
    assert bridge.started == ["srv-1", "srv-2"]


async def test_activate_rolls_back_on_mcp_failure() -> None:
    skill = _make_skill(
        "gh",
        mcp_servers=[
            MCPServerDef(command="ok"),
            MCPServerDef(command="bad"),
        ],
    )
    controller, bridge, catalog = _controller({"gh": skill})
    bridge.start_raises["bad"] = RuntimeError("stdio closed")
    result = await controller.activate("gh")
    assert not result.success
    assert "mcp-error" in result.reason
    assert catalog.skills["gh"].active is False
    assert bridge.started == ["srv-1"]
    assert bridge.stopped == ["srv-1"]


async def test_deactivate_unknown_skill_returns_failure() -> None:
    controller, _, _ = _controller({})
    result = await controller.deactivate("nope")
    assert result == ActivationResult(False, "unknown-skill")


async def test_deactivate_already_inactive_is_idempotent() -> None:
    controller, bridge, _ = _controller({"hello": _make_skill("hello")})
    result = await controller.deactivate("hello")
    assert result == ActivationResult(True, "already-inactive")
    assert bridge.stopped == []


async def test_deactivate_stops_started_mcp_servers() -> None:
    skill = _make_skill(
        "gh", mcp_servers=[MCPServerDef(command="gh-mcp")]
    )
    controller, bridge, catalog = _controller({"gh": skill})
    await controller.activate("gh")
    await controller.deactivate("gh")
    assert catalog.skills["gh"].active is False
    assert bridge.stopped == ["srv-1"]


async def test_deactivate_reports_cleanup_errors_as_nonfatal() -> None:
    skill = _make_skill(
        "gh", mcp_servers=[MCPServerDef(command="gh-mcp")]
    )
    controller, bridge, catalog = _controller({"gh": skill})
    await controller.activate("gh")
    bridge.stop_raises["srv-1"] = RuntimeError("pipe broken")
    result = await controller.deactivate("gh")
    assert result == ActivationResult(True, "deactivated-with-cleanup-errors")
    assert catalog.skills["gh"].active is False


async def test_active_names_returns_only_active() -> None:
    controller, _, _ = _controller(
        {
            "alpha": _make_skill("alpha"),
            "beta": _make_skill("beta"),
            "gamma": _make_skill("gamma"),
        }
    )
    await controller.activate("alpha")
    await controller.activate("gamma")
    assert sorted(controller.active_names()) == ["alpha", "gamma"]


async def test_subscribers_fire_on_activate_and_deactivate() -> None:
    controller, _, _ = _controller({"hello": _make_skill("hello")})
    calls: list[str] = []
    controller.subscribe(lambda: calls.append("tick"))
    await controller.activate("hello")
    await controller.deactivate("hello")
    assert calls == ["tick", "tick"]


async def test_subscribers_continue_after_one_raises() -> None:
    controller, _, _ = _controller({"hello": _make_skill("hello")})
    calls: list[str] = []
    controller.subscribe(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    controller.subscribe(lambda: calls.append("second"))
    await controller.activate("hello")
    assert calls == ["second"]


async def test_unsubscribe_removes_listener() -> None:
    controller, _, _ = _controller({"hello": _make_skill("hello")})
    calls: list[str] = []
    unsubscribe = controller.subscribe(lambda: calls.append("tick"))
    unsubscribe()
    await controller.activate("hello")
    assert calls == []


async def test_unsubscribe_is_idempotent() -> None:
    controller, _, _ = _controller({"hello": _make_skill("hello")})
    unsubscribe = controller.subscribe(lambda: None)
    unsubscribe()
    unsubscribe()


async def test_activate_persists_to_store_when_configured(tmp_path: Path) -> None:
    controller, _, _ = _controller(
        {"hello": _make_skill("hello")}, tmp_path=tmp_path
    )
    await controller.activate("hello")
    assert controller._store is not None  # noqa: SLF001
    await controller._store.drain_pending()  # noqa: SLF001
    assert controller._store.load() == ["hello"]  # noqa: SLF001


async def test_failed_activation_does_not_persist(tmp_path: Path) -> None:
    skill = _make_skill(
        "gh", mcp_servers=[MCPServerDef(command="bad")]
    )
    controller, bridge, _ = _controller({"gh": skill}, tmp_path=tmp_path)
    bridge.start_raises["bad"] = RuntimeError("no")
    await controller.activate("gh")
    assert controller._store is not None  # noqa: SLF001
    await controller._store.drain_pending()  # noqa: SLF001
    assert controller._store.load() == []  # noqa: SLF001


async def test_activate_many_returns_per_name_results() -> None:
    controller, _, _ = _controller(
        {
            "alpha": _make_skill("alpha"),
            "beta": _make_skill("beta"),
        }
    )
    results = await controller.activate_many(["alpha", "beta", "missing"])
    assert results["alpha"].success
    assert results["beta"].success
    assert not results["missing"].success


async def test_activate_many_continues_after_failure() -> None:
    skill_a = _make_skill("alpha", mcp_servers=[MCPServerDef(command="bad")])
    skill_b = _make_skill("beta")
    controller, bridge, catalog = _controller({"alpha": skill_a, "beta": skill_b})
    bridge.start_raises["bad"] = RuntimeError("no")
    await controller.activate_many(["alpha", "beta"])
    assert catalog.skills["alpha"].active is False
    assert catalog.skills["beta"].active is True


async def test_reload_reports_added_and_removed_skills() -> None:
    controller, _, _ = _controller({"alpha": _make_skill("alpha")})
    await controller.activate("alpha")

    def _discover() -> dict[str, Skill]:
        return {"alpha": _make_skill("alpha"), "beta": _make_skill("beta")}

    result = await controller.reload_from_disk(_discover)
    assert result.added == ["beta"]
    assert result.removed == []
    assert result.preserved == ["alpha"]


async def test_reload_deactivates_vanished_skills_and_stops_mcp() -> None:
    skill_a = _make_skill("alpha", mcp_servers=[MCPServerDef(command="mcp-a")])
    controller, bridge, catalog = _controller({"alpha": skill_a})
    await controller.activate("alpha")

    result = await controller.reload_from_disk(lambda: {})
    assert result.removed == ["alpha"]
    assert bridge.stopped == ["srv-1"]
    assert "alpha" not in catalog.skills


async def test_reload_records_mcp_cleanup_failures() -> None:
    skill_a = _make_skill("alpha", mcp_servers=[MCPServerDef(command="mcp-a")])
    controller, bridge, _ = _controller({"alpha": skill_a})
    await controller.activate("alpha")
    bridge.stop_raises["srv-1"] = RuntimeError("pipe")

    result = await controller.reload_from_disk(lambda: {})
    assert result.deactivation_failures == ["alpha"]


async def test_reload_preserves_active_flag_for_still_present_skills() -> None:
    controller, _, _ = _controller({"alpha": _make_skill("alpha")})
    await controller.activate("alpha")

    def _discover() -> dict[str, Skill]:
        return {"alpha": _make_skill("alpha")}

    await controller.reload_from_disk(_discover)
    assert controller.catalog.skills["alpha"].active is True


async def test_reload_fires_subscribers_once() -> None:
    controller, _, _ = _controller({"alpha": _make_skill("alpha")})
    await controller.activate("alpha")

    calls: list[str] = []
    controller.subscribe(lambda: calls.append("tick"))

    await controller.reload_from_disk(lambda: {"alpha": _make_skill("alpha")})
    assert calls == ["tick"]


async def test_catalog_property_exposes_underlying_catalog() -> None:
    skills = {"alpha": _make_skill("alpha")}
    controller, _, _ = _controller(skills)
    assert controller.catalog.skills == skills
