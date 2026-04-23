"""Integration test: SkillController drives MCPBridge start/stop on toggle.

Closes the mechanism gap that the UI toggle previously left open —
requirements §119 "auto-start MCP on activation" and §121 "clean up on
deactivation". Uses the echo server fixture and a real :class:`MCPBridge`
(no mocks on the bridge side) so the test catches regressions where a
future refactor skips the MCP hookup.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stoiquent.models import PersistenceConfig
from stoiquent.skills.active_store import ActiveSkillsStore
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.controller import SkillController
from stoiquent.skills.mcp_bridge import MCPBridge
from stoiquent.skills.models import MCPServerDef, Skill, SkillMeta

ECHO_SERVER = str(
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mcp_servers"
    / "echo_server.py"
)


def _echo_skill() -> Skill:
    return Skill(
        meta=SkillMeta(
            name="echo-skill",
            description="Skill backed by MCP echo server",
            mcp_servers=[
                MCPServerDef(command=sys.executable, args=[ECHO_SERVER])
            ],
        ),
        path=Path("/skills/echo-skill"),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_starts_and_stops_mcp_server_on_toggle() -> None:
    bridge = MCPBridge()
    catalog = SkillCatalog({"echo-skill": _echo_skill()})
    controller = SkillController(catalog, bridge)

    try:
        assert bridge.server_ids == []
        result = await controller.activate("echo-skill")
        assert result.success, result.reason
        assert catalog.skills["echo-skill"].active is True
        assert len(bridge.server_ids) == 1
        server_id = bridge.server_ids[0]
        tool_names = {
            t["function"]["name"] for t in bridge.get_tools(server_id)
        }
        assert "echo" in tool_names

        result = await controller.deactivate("echo-skill")
        assert result.success, result.reason
        assert catalog.skills["echo-skill"].active is False
        assert bridge.server_ids == []
    finally:
        await bridge.stop_all()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_persists_active_set_across_instances(
    tmp_path: Path,
) -> None:
    bridge = MCPBridge()
    store = ActiveSkillsStore(PersistenceConfig(data_dir=str(tmp_path)))
    catalog = SkillCatalog({"echo-skill": _echo_skill()})
    controller = SkillController(catalog, bridge, store)

    try:
        await controller.activate("echo-skill")
        await store.drain_pending()
        assert store.load() == ["echo-skill"]
    finally:
        await bridge.stop_all()

    fresh_bridge = MCPBridge()
    fresh_catalog = SkillCatalog({"echo-skill": _echo_skill()})
    fresh_controller = SkillController(fresh_catalog, fresh_bridge, store)
    try:
        restore_results = await fresh_controller.activate_many(store.load())
        assert all(r.success for r in restore_results.values())
        assert fresh_catalog.skills["echo-skill"].active is True
        assert len(fresh_bridge.server_ids) == 1
    finally:
        await fresh_bridge.stop_all()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_reload_drops_vanished_skill_and_stops_its_mcp(
    tmp_path: Path,
) -> None:
    bridge = MCPBridge()
    store = ActiveSkillsStore(PersistenceConfig(data_dir=str(tmp_path)))
    catalog = SkillCatalog({"echo-skill": _echo_skill()})
    controller = SkillController(catalog, bridge, store)

    try:
        await controller.activate("echo-skill")
        assert len(bridge.server_ids) == 1

        result = await controller.reload_from_disk(lambda: {})
        assert result.removed == ["echo-skill"]
        assert bridge.server_ids == []
        assert "echo-skill" not in catalog.skills
    finally:
        await bridge.stop_all()
