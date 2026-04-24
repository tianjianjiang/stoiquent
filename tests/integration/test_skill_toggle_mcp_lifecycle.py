"""Integration test: SkillController drives MCPBridge start/stop on toggle.

Closes the mechanism gap that the UI toggle previously left open —
requirements §119 "auto-start MCP on activation" and §121 "clean up on
deactivation". Uses the echo server fixture and a real :class:`MCPBridge`
(no mocks on the bridge side) so the test catches regressions where a
future refactor skips the MCP hookup.
"""
from __future__ import annotations

import logging
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

# Substrings emitted by the ``stop_server`` and ``_reap_pgroup`` paths
# in stoiquent/skills/mcp_bridge.py when reap needed SIGKILL escalation
# or raised during cleanup. If any appear in caplog, the bridge left
# orphans the graceful stop couldn't reclaim — the exact case the
# integration test's try/finally pattern would otherwise mask by
# swallowing the bridge's WARNING/ERROR records.
#
# Not covered here (deliberately out of scope for this guard):
#   * init-time pgrep-unusable WARNINGs (fire once at MCPBridge() time,
#     not during stop_all).
#   * wrapper-command zombies with zero tracked PIDs (would require an
#     OS-level child-PID snapshot to detect; tracked for follow-up).
_BRIDGE_CLEANUP_FAILURE_MARKERS: tuple[str, ...] = (
    "required SIGKILL fallback",
    "reap raised",
    "cleanup failed",
    "could not SIGKILL orphan",
)


def _assert_bridge_cleanly_drained(
    bridge: MCPBridge, caplog: pytest.LogCaptureFixture
) -> None:
    """Assert no leaked MCP subprocesses after ``stop_all``.

    ``MCPBridge.stop_server`` wraps ``session.aclose`` and the pgroup
    reap in ``try/except`` blocks that log at WARNING/ERROR and
    continue, so a subprocess leak previously showed only as a log
    record that the test would discard. This helper checks both the
    bookkeeping invariant (``bridge.server_ids == []``) and the
    observability channel (no record in
    :data:`_BRIDGE_CLEANUP_FAILURE_MARKERS`). ``caplog.clear()`` after
    assertion prevents cross-test bleed on shared fixtures."""
    assert bridge.server_ids == [], (
        f"bridge still tracks server ids after stop_all: {bridge.server_ids}"
    )
    leaked = [
        r for r in caplog.records
        if r.name.startswith("stoiquent.skills.mcp_bridge")
        and r.levelno >= logging.WARNING
        and any(m in r.getMessage() for m in _BRIDGE_CLEANUP_FAILURE_MARKERS)
    ]
    assert not leaked, (
        f"MCPBridge logged a subprocess-leak warning; orphan left behind: "
        f"{[r.getMessage() for r in leaked]!r}"
    )
    caplog.clear()


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
async def test_controller_starts_and_stops_mcp_server_on_toggle(
    caplog: pytest.LogCaptureFixture,
) -> None:
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
    finally:
        with caplog.at_level(logging.WARNING, logger="stoiquent.skills.mcp_bridge"):
            await bridge.stop_all()
        _assert_bridge_cleanly_drained(bridge, caplog)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_persists_active_set_across_instances(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
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
        with caplog.at_level(logging.WARNING, logger="stoiquent.skills.mcp_bridge"):
            await bridge.stop_all()
        _assert_bridge_cleanly_drained(bridge, caplog)

    fresh_bridge = MCPBridge()
    fresh_catalog = SkillCatalog({"echo-skill": _echo_skill()})
    fresh_controller = SkillController(fresh_catalog, fresh_bridge, store)
    try:
        restore_results = await fresh_controller.activate_many(store.load())
        assert all(r.success for r in restore_results.values())
        assert fresh_catalog.skills["echo-skill"].active is True
        assert len(fresh_bridge.server_ids) == 1
    finally:
        with caplog.at_level(logging.WARNING, logger="stoiquent.skills.mcp_bridge"):
            await fresh_bridge.stop_all()
        _assert_bridge_cleanly_drained(fresh_bridge, caplog)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_reload_drops_vanished_skill_and_stops_its_mcp(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
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
        assert "echo-skill" not in catalog.skills
    finally:
        with caplog.at_level(logging.WARNING, logger="stoiquent.skills.mcp_bridge"):
            await bridge.stop_all()
        _assert_bridge_cleanly_drained(bridge, caplog)
