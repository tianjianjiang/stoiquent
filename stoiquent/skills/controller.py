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
    a machine-readable reason — either ``"unknown-skill"`` or a
    ``"mcp-error: ..."`` prefix whose suffix is the formatted exception
    (the suffix is not a stable contract — UIs should match on the
    prefix only).

    ``warnings`` is a tuple of short human-readable strings describing
    partial failures the user should see even on ``success=True`` — for
    example, an MCP server that failed to stop during deactivation, or
    a server that leaked during rollback of a failed activation. UI
    callers MUST render warnings regardless of ``success`` so silent
    subprocess leaks don't go unnoticed.
    """

    success: bool
    reason: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReloadResult:
    """Outcome of :meth:`SkillController.reload_from_disk`.

    Use ``added``/``removed`` to render toast summaries; use
    ``deactivation_failures`` to warn about MCP cleanup that raised
    during reconciliation. ``deactivation_failures`` is a sorted list
    with no duplicates — a skill is listed at most once even if several
    of its MCP servers failed to stop.

    ``warnings`` mirrors :attr:`ActivationResult.warnings` — a tuple of
    human-readable strings describing leaked subprocesses or cleanup
    problems the user should see. UI callers MUST render warnings. One
    warning is emitted per entry in ``deactivation_failures``, in the
    same sort order (skill-name asc), so callers can correlate them by
    index. This pairing is enforced at construction (``ValueError`` on
    length mismatch). Warnings use the same format as the deactivate-
    cleanup message on :class:`ActivationResult`; the activate-rollback
    message on :class:`ActivationResult` uses a distinct shape.
    """

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    deactivation_failures: list[str] = field(default_factory=list)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.warnings) != len(self.deactivation_failures):
            raise ValueError(
                f"ReloadResult.warnings ({len(self.warnings)}) must pair "
                f"1:1 with deactivation_failures "
                f"({len(self.deactivation_failures)})"
            )


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

    The lock is deliberately held across :meth:`MCPBridge.start_server`
    and :meth:`MCPBridge.stop_server`. Those calls spawn a subprocess,
    open stdio pipes, and await ``session.initialize`` +
    ``session.list_tools`` — so a slow-to-spawn skill blocks every
    other surface's toggle for the duration. This trades responsiveness
    for the ``_skill_servers`` ↔ catalog consistency guarantee; a
    future optimization to move MCP calls outside the lock must
    preserve that invariant (e.g. via per-skill locks keyed by name).
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
            except BaseException as exc:
                # Catch BaseException — asyncio.CancelledError inherits from
                # BaseException (not Exception) in Python 3.8+, so catching
                # only Exception would leak started subprocesses on
                # cancellation.
                logger.exception(
                    "Failed to start MCP servers for skill %s; rolling back",
                    name,
                )
                rollback_failures: list[str] = []
                for sid in started:
                    try:
                        await self._mcp.stop_server(sid)
                    except BaseException as rollback_exc:
                        rollback_failures.append(sid)
                        logger.exception(
                            "Failed to stop partially-started MCP server %s "
                            "for skill %s",
                            sid,
                            name,
                        )
                        # Shutdown signals raised by stop_server itself must
                        # continue to propagate — don't let best-effort
                        # rollback convert them into warnings.
                        if not isinstance(rollback_exc, Exception):
                            raise
                warnings = (
                    (
                        f"MCP rollback leaked {len(rollback_failures)} server(s) "
                        f"for '{name}': {','.join(rollback_failures)}",
                    )
                    if rollback_failures
                    else ()
                )
                if not isinstance(exc, Exception):
                    raise
                return ActivationResult(
                    False, f"mcp-error: {exc}", warnings=warnings
                )

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
            failed_ids: list[str] = []
            for sid in server_ids:
                try:
                    await self._mcp.stop_server(sid)
                except BaseException as cleanup_exc:
                    failed_ids.append(sid)
                    logger.exception(
                        "Failed to stop MCP server %s for skill %s", sid, name
                    )
                    # Shutdown signals raised by stop_server itself must
                    # continue to propagate — cleanup errors should never
                    # swallow a KeyboardInterrupt.
                    if not isinstance(cleanup_exc, Exception):
                        raise

            self._catalog.deactivate(name)
            self._persist()

        self._notify()
        if failed_ids:
            return ActivationResult(
                True,
                "deactivated-with-cleanup-errors",
                warnings=(
                    f"MCP cleanup failed for '{name}': "
                    f"{','.join(failed_ids)} — subprocess(es) may still be running",
                ),
            )
        return ActivationResult(True, "deactivated")

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
        """Re-run ``discover`` and reconcile the catalog via
        :meth:`SkillCatalog.replace`.

        Reconciliation semantics:

        - Skills absent from the new discovery set are **dropped from
          the catalog entirely** (not put through
          :meth:`deactivate`); their MCP servers are stopped
          synchronously.
        - Skills that remain keep their active flag — they are
          re-cloned with ``active=True`` in the new catalog.
        - Newly-discovered skills start inactive.

        Subscribers fire exactly once after the full swap, not per
        skill. ``deactivation_failures`` lists (sorted, deduplicated)
        names whose MCP cleanup raised — the catalog swap proceeds
        regardless. UI callers MUST render :attr:`ReloadResult.warnings`
        (richer than ``deactivation_failures`` — includes the leaked
        server IDs) so the user can reap orphan subprocesses manually.
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

            deactivation_failures_set: set[str] = set()
            failed_by_skill: dict[str, list[str]] = {}
            for name in vanished_active:
                server_ids = self._skill_servers.pop(name, [])
                for sid in server_ids:
                    try:
                        await self._mcp.stop_server(sid)
                    except BaseException as cleanup_exc:
                        deactivation_failures_set.add(name)
                        failed_by_skill.setdefault(name, []).append(sid)
                        logger.exception(
                            "Failed to stop MCP server %s for vanished skill %s",
                            sid,
                            name,
                        )
                        # Shutdown signals (KeyboardInterrupt, SystemExit,
                        # CancelledError) must propagate — reconciliation
                        # errors should never swallow a signal.
                        if not isinstance(cleanup_exc, Exception):
                            raise

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
        warnings = tuple(
            f"MCP cleanup failed for '{skill_name}': "
            f"{','.join(sids)} — subprocess(es) may still be running"
            for skill_name, sids in sorted(failed_by_skill.items())
        )
        return ReloadResult(
            added=added,
            removed=removed,
            preserved=preserved_active,
            deactivation_failures=sorted(deactivation_failures_set),
            warnings=warnings,
        )

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save_background(self.active_names())

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            try:
                cb()
            except Exception:
                logger.exception(
                    "SkillController subscriber %r raised during notify", cb
                )
