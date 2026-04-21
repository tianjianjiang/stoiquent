from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stoiquent.models import SAFE_ID, PersistenceConfig

logger = logging.getLogger(__name__)


class ProjectLoadError(Exception):
    """A project file exists but cannot be parsed or read.

    Distinct from "project not found" (which `load` returns as `None`):
    this signals damaged JSON, schema-invalid data, or an I/O error on an
    existing file. Callers should render a "data damaged" message, not
    "not found", so users can distinguish a delete race from a repair need.
    """


class ProjectDeleteResult(enum.Enum):
    """Tri-state outcome of `ProjectStore.delete`.

    `ALREADY_GONE` is desired-state-met (idempotent delete / race with
    concurrent cleanup); callers can silently succeed. `FAILED` is a real
    I/O failure and should notify the user.
    """

    DELETED = "deleted"
    ALREADY_GONE = "already_gone"
    FAILED = "failed"


def _validate_safe_id(v: str) -> str:
    if not SAFE_ID.match(v):
        raise ValueError(f"Invalid project id: {v!r}")
    return v


class ProjectRecord(BaseModel):
    """Full project stored as a single JSON file."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    instructions: str = ""
    memory: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    validate_id = field_validator("id")(_validate_safe_id)


class ProjectSummary(BaseModel):
    """Lightweight metadata for sidebar listing."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    created_at: str
    updated_at: str

    validate_id = field_validator("id")(_validate_safe_id)


class ProjectStore:
    """File-backed project persistence. One JSON file per project."""

    def __init__(self, config: PersistenceConfig) -> None:
        self._base_dir = Path(config.data_dir).expanduser().resolve()
        self._projects_dir = self._base_dir / "projects"
        self._pending_tasks: set[asyncio.Task[None]] = set()

    def ensure_dirs(self) -> None:
        """Create data directories. Call once at startup."""
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, project_id: str) -> Path:
        if not SAFE_ID.match(project_id):
            raise ValueError(f"Invalid project_id: {project_id!r}")
        return self._projects_dir / f"{project_id}.json"

    def save_sync(self, project: ProjectRecord) -> None:
        """Save project atomically via tempfile + os.replace.

        On update (target file exists and loads successfully), created_at is
        preserved from the existing record; updated_at is refreshed to now.
        If the existing file is missing, unreadable, or schema-invalid, the
        caller's created_at is kept.
        """
        project = project.model_copy(
            update={"updated_at": datetime.now(timezone.utc).isoformat()}
        )

        path = self._path_for(project.id)
        if path.exists():
            try:
                existing = self.load(project.id)
            except ProjectLoadError:
                # Existing file is damaged; we will overwrite it rather than
                # refuse to save. Log loudly because the caller's
                # created_at wins, destroying whatever the damaged file
                # held — this is the one place that decision is made.
                logger.warning(
                    "Project %s has a damaged on-disk copy; save_sync will "
                    "overwrite it. created_at from the prior record cannot "
                    "be recovered.",
                    project.id,
                )
                existing = None
            if existing is not None:
                project = project.model_copy(
                    update={"created_at": existing.created_at}
                )

        data = project.model_dump_json(indent=2)
        fd = -1
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self._projects_dir, suffix=".tmp", prefix=f".{project.id}_"
            )
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp_path, path)
        except BaseException:
            # Defensive cleanup: never let cleanup errors mask the original exception.
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    logger.warning(
                        "Failed to close tempfile fd for %s", project.id, exc_info=True
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

    async def save(self, project: ProjectRecord) -> None:
        """Async save via thread pool."""
        await asyncio.to_thread(self.save_sync, project)

    async def drain_pending(self) -> None:
        """Await save_background tasks pending at call time.

        Exceptions from individual tasks are suppressed (they are already
        logged inside save_background). Tasks scheduled after this call
        begins awaiting are not drained.
        """
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)

    def save_background(self, project: ProjectRecord) -> None:
        """Fire-and-forget save. Deep-copies the project, then schedules an
        async save on the running loop (tracked in ``_pending_tasks``) or
        falls back to save_sync when no loop is running. All errors are
        logged and suppressed; await `drain_pending` to wait for in-flight
        tasks.
        """
        project = project.model_copy(deep=True)

        async def _do_save() -> None:
            try:
                await self.save(project)
            except Exception:
                logger.exception("Failed to save project %s", project.id)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_save())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            try:
                self.save_sync(project)
            except Exception:
                logger.exception(
                    "Failed to save project %s (sync fallback)", project.id
                )

    def load(self, project_id: str) -> ProjectRecord | None:
        """Load a project by ID.

        Returns `None` only when the project file is genuinely absent.
        Raises `ProjectLoadError` when the file exists but cannot be read
        or parsed — callers should treat that as "data damaged, needs
        repair", not "not found".
        """
        path = self._path_for(project_id)
        if not path.exists():
            return None
        try:
            data = path.read_text(encoding="utf-8")
            return ProjectRecord.model_validate_json(data)
        except FileNotFoundError:
            # Race: file was deleted between exists() and read_text().
            # Classify as "not found", matching the exists()-was-false case.
            return None
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning(
                "Failed to load project %s", project_id, exc_info=True
            )
            raise ProjectLoadError(
                f"Project {project_id!r} exists but could not be loaded"
            ) from e

    async def load_async(self, project_id: str) -> ProjectRecord | None:
        """Async variant of load via thread pool. Same exception contract as `load`."""
        return await asyncio.to_thread(self.load, project_id)

    def list_projects(self) -> list[ProjectSummary]:
        """List all saved projects, sorted by updated_at descending."""
        summaries: list[ProjectSummary] = []
        if not self._projects_dir.exists():
            return summaries

        for path in self._projects_dir.glob("*.json"):
            try:
                record = ProjectRecord.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                if record.id != path.stem:
                    logger.warning(
                        "Skipping project file %s: id %r does not match filename",
                        path.name,
                        record.id,
                    )
                    continue
                summaries.append(
                    ProjectSummary(
                        id=record.id,
                        name=record.name,
                        folder=record.folder,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
            except (OSError, ValueError):
                logger.warning(
                    "Skipping unreadable project file: %s",
                    path.name,
                    exc_info=True,
                )

        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    async def list_projects_async(self) -> list[ProjectSummary]:
        """Async variant of list_projects via thread pool."""
        return await asyncio.to_thread(self.list_projects)

    def delete(self, project_id: str) -> ProjectDeleteResult:
        """Delete a project file. See `ProjectDeleteResult` for the three outcomes."""
        path = self._path_for(project_id)
        try:
            path.unlink()
            return ProjectDeleteResult.DELETED
        except FileNotFoundError:
            return ProjectDeleteResult.ALREADY_GONE
        except OSError:
            logger.warning(
                "Failed to delete project %s", project_id, exc_info=True
            )
            return ProjectDeleteResult.FAILED
