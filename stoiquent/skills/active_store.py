from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stoiquent.models import PersistenceConfig

logger = logging.getLogger(__name__)


class ActiveSkillsLoadError(Exception):
    """active_skills.json exists but cannot be parsed or read.

    Distinct from absence (which `load` returns as an empty list):
    this signals damaged JSON, schema-invalid data, or I/O error. Callers
    should decide whether to abort startup or fall back to an empty
    active set, not silently mistake damage for 'no skills were active'.
    """


class ActiveSkillsRecord(BaseModel):
    """Set of currently-active skill names, persisted across restarts."""

    model_config = ConfigDict(extra="forbid")

    active: list[str] = Field(default_factory=list)
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ActiveSkillsStore:
    """Single-file persistence of the active-skill set at
    ``<data_dir>/active_skills.json``. Atomic writes via tempfile + os.replace."""

    _FILENAME = "active_skills.json"

    def __init__(self, config: PersistenceConfig) -> None:
        self._base_dir = Path(config.data_dir).expanduser().resolve()
        self._path = self._base_dir / self._FILENAME
        self._pending_tasks: set[asyncio.Task[None]] = set()
        # Serializes concurrent save tasks so rapid toggles don't end up
        # writing stale state last. Without this, two tasks saving
        # different snapshots race via os.replace and the final on-disk
        # state depends on task completion order.
        self._save_lock = asyncio.Lock()

    def ensure_dirs(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[str]:
        """Return persisted active-skill names, or ``[]`` when absent.

        Raises:
            ActiveSkillsLoadError: file exists but cannot be read or parsed.
        """
        if not self._path.exists():
            return []
        try:
            data = self._path.read_text(encoding="utf-8")
            record = ActiveSkillsRecord.model_validate_json(data)
            return list(record.active)
        except FileNotFoundError:
            logger.info(
                "active_skills.json vanished between exists() and read_text() "
                "(external edit or concurrent write race)"
            )
            return []
        except (json.JSONDecodeError, OSError, ValueError, ValidationError) as e:
            logger.warning("Failed to load active_skills.json", exc_info=True)
            raise ActiveSkillsLoadError(
                f"active_skills.json at {self._path} exists but could not be loaded"
            ) from e

    async def load_async(self) -> list[str]:
        return await asyncio.to_thread(self.load)

    def quarantine_damaged(self) -> Path | None:
        """Rename a damaged ``active_skills.json`` to a timestamped sidecar.

        Call after :meth:`load` raises :class:`ActiveSkillsLoadError` so
        the next :meth:`save_sync` doesn't overwrite the corrupt contents
        with a fresh empty-or-partial state. The sidecar
        (``active_skills.json.corrupt-<ISO-8601>``) preserves the
        original bytes for the user to inspect or restore manually.

        Returns the sidecar path on success, or ``None`` when the source
        file is missing or the rename itself fails (e.g. EPERM). The
        failure is logged but not raised because this method runs in
        a post-error recovery path and must never itself abort startup.
        """
        if not self._path.exists():
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        sidecar = self._path.with_name(f"{self._path.name}.corrupt-{timestamp}")
        # Sub-second collisions (rapid restart loop, supervisord respawn)
        # would silently clobber the prior sidecar via os.replace; bump
        # a numeric suffix so each corrupt snapshot survives for the
        # manual inspection the docstring promises.
        counter = 0
        while sidecar.exists():
            counter += 1
            sidecar = self._path.with_name(
                f"{self._path.name}.corrupt-{timestamp}.{counter}"
            )
        try:
            os.replace(self._path, sidecar)
        except OSError:
            logger.exception(
                "Failed to quarantine damaged active_skills.json at %s",
                self._path,
            )
            return None
        return sidecar

    def save_sync(self, active: list[str]) -> None:
        record = ActiveSkillsRecord(
            active=sorted(set(active)),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        data = record.model_dump_json(indent=2)

        self._base_dir.mkdir(parents=True, exist_ok=True)
        fd = -1
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self._base_dir, suffix=".tmp", prefix=".active_skills_"
            )
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp_path, self._path)
        except BaseException:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    logger.warning(
                        "Failed to close tempfile fd for active_skills.json",
                        exc_info=True,
                    )
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.warning(
                        "Failed to unlink tempfile %s", tmp_path, exc_info=True
                    )
            raise

    async def save(self, active: list[str]) -> None:
        async with self._save_lock:
            await asyncio.to_thread(self.save_sync, list(active))

    def save_background(self, active: list[str]) -> None:
        """Fire-and-forget save. Snapshots ``active`` so in-flight mutations
        don't corrupt the pending write, and routes through :meth:`save`
        so concurrent calls are serialized by ``_save_lock`` in FIFO
        order. Errors are logged and suppressed; await ``drain_pending``
        to wait for in-flight tasks."""
        snapshot = list(active)

        async def _do_save() -> None:
            try:
                await self.save(snapshot)
            except Exception:
                logger.exception("Failed to save active_skills.json")

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_save())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            try:
                self.save_sync(snapshot)
            except Exception:
                logger.exception(
                    "Failed to save active_skills.json (sync fallback)"
                )

    async def drain_pending(self) -> None:
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
