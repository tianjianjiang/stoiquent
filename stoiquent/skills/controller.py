from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.mcp_bridge import MCPBridge

if TYPE_CHECKING:
    from stoiquent.skills.active_store import ActiveSkillsStore
    from stoiquent.skills.models import Skill

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActivationResult:
    """Outcome of :meth:`SkillController.activate` or ``deactivate``.

    ``success=True`` with ``reason in {"activated", "already-active",
    "deactivated", "already-inactive", "deactivated-with-cleanup-errors"}``
    means the skill is in the requested state. ``success=False`` carries
    a human-readable reason (``"unknown-skill"`` or ``"mcp-error: ..."``)
    suitable for ``ui.notify``.
    """

    success: bool
    reason: str


@dataclass(frozen=True)
class ReloadResult:
    """Outcome of :meth:`SkillController.reload_from_disk`.

    Use ``added``/``removed`` to render toast summaries; use
    ``deactivation_failures`` to warn about MCP cleanup that raised
    during reconciliation.
    """

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    deactivation_failures: list[str] = field(default_factory=list)


class SkillController:
    """Single source of truth for skill activation.

    Composes :class:`SkillCatalog` (in-memory state) with
    :class:`MCPBridge` (server lifecycle) and optional
    :class:`ActiveSkillsStore` (persistence). All UI surfaces should
    mutate state via this controller and re-render via ``subscribe``.

    Activation is serialized by an internal ``asyncio.Lock`` so that
    concurrent toggles from different surfaces (header menu, manager
    dialog, sidebar) can't interleave MCP start/stop with catalog
    mutations.
    """

    def __init__(
        self,
        catalog: SkillCatalog,
        mcp_bridge: MCPBridge,
        active_store: ActiveSkillsStore | None = None,
    ) -> None:
        self._catalog = catalog
        self._mcp = mcp_bridge
        self._store = active_store
        self._skill_servers: dict[str, list[str]] = {}
        self._subscribers: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()

    @property
    def catalog(self) -> SkillCatalog:
        return self._catalog

    def active_names(self) -> list[str]:
        return [s.meta.name for s in self._catalog.get_active_skills()]

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a change listener. Returns an unsubscribe callable.

        Callbacks run synchronously after each state mutation; exceptions
        are logged and do not propagate to other subscribers.
        """
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    async def activate(self, name: str) -> ActivationResult:
        async with self._lock:
            skill = self._catalog.skills.get(name)
            if skill is None:
                return ActivationResult(False, "unknown-skill")
            if skill.active:
                return ActivationResult(True, "already-active")

            started: list[str] = []
            try:
                for server_def in skill.meta.mcp_servers:
                    server_id = await self._mcp.start_server(server_def)
                    started.append(server_id)
            except Exception as exc:
                logger.exception(
                    "Failed to start MCP servers for skill %s; rolling back", name
                )
                for sid in started:
                    try:
                        await self._mcp.stop_server(sid)
                    except Exception:
                        logger.exception(
                            "Failed to stop partially-started MCP server %s", sid
                        )
                return ActivationResult(False, f"mcp-error: {exc}")

            self._skill_servers[name] = started
            self._catalog.activate(name)
            self._persist()

        self._notify()
        return ActivationResult(True, "activated")

    async def deactivate(self, name: str) -> ActivationResult:
        async with self._lock:
            skill = self._catalog.skills.get(name)
            if skill is None:
                return ActivationResult(False, "unknown-skill")
            if not skill.active:
                return ActivationResult(True, "already-inactive")

            server_ids = self._skill_servers.pop(name, [])
            cleanup_failed = False
            for sid in server_ids:
                try:
                    await self._mcp.stop_server(sid)
                except Exception:
                    cleanup_failed = True
                    logger.exception(
                        "Failed to stop MCP server %s for skill %s", sid, name
                    )

            self._catalog.deactivate(name)
            self._persist()

        self._notify()
        reason = (
            "deactivated-with-cleanup-errors" if cleanup_failed else "deactivated"
        )
        return ActivationResult(True, reason)

    async def activate_many(self, names: list[str]) -> dict[str, ActivationResult]:
        """Activate several skills in sequence. Returns per-name outcomes so
        callers (e.g. app startup restore) can report partial failures without
        aborting the remaining activations."""
        results: dict[str, ActivationResult] = {}
        for name in names:
            results[name] = await self.activate(name)
        return results

    async def reload_from_disk(
        self, discover: Callable[[], dict[str, Skill]]
    ) -> ReloadResult:
        """Re-run ``discover`` and reconcile the catalog with the result.

        Skills that disappeared while active are deactivated (their MCP
        servers are stopped). Skills that remain keep their active flag.
        Newly-discovered skills start inactive.
        """
        async with self._lock:
            prev_active = {s.meta.name for s in self._catalog.get_active_skills()}
            prev_names = set(self._catalog.skills)
            new_skills = discover()
            new_names = set(new_skills)

            added = sorted(new_names - prev_names)
            removed = sorted(prev_names - new_names)
            preserved_active = sorted(prev_active & new_names)
            vanished_active = sorted(prev_active - new_names)

            deactivation_failures: list[str] = []
            for name in vanished_active:
                server_ids = self._skill_servers.pop(name, [])
                for sid in server_ids:
                    try:
                        await self._mcp.stop_server(sid)
                    except Exception:
                        deactivation_failures.append(name)
                        logger.exception(
                            "Failed to stop MCP server %s for vanished skill %s",
                            sid,
                            name,
                        )

            reconciled: dict[str, Skill] = {}
            for name, skill in new_skills.items():
                if name in preserved_active:
                    reconciled[name] = skill.model_copy(update={"active": True})
                else:
                    reconciled[name] = skill
            self._catalog.replace(reconciled)

            for name in list(self._skill_servers):
                if name not in new_names:
                    self._skill_servers.pop(name, None)

            self._persist()

        self._notify()
        return ReloadResult(
            added=added,
            removed=removed,
            preserved=preserved_active,
            deactivation_failures=deactivation_failures,
        )

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save_background(self.active_names())

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            try:
                cb()
            except Exception:
                logger.exception("SkillController subscriber raised")
