from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stoiquent.models import SAFE_ID, Message, PersistenceConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteByProjectResult:
    """Outcome of cascading conversation deletion for a project.

    The cascade is considered complete only when
    ``unlink_failed == skipped_unparseable == skipped_unreadable == 0``.
    Callers that must not leave orphan sessions (see user requirement:
    "delete project means deleting everything") should refuse to advance
    to the project-record delete unless :attr:`complete` is ``True``.

    :attr:`complete` signals it is safe for the caller to proceed with
    the project-record delete under the orphan-free invariant; it does
    not by itself prove no orphans exist on disk. Frozen so consumers
    cannot mutate counters past the gate.
    """

    deleted: int = 0
    unlink_failed: int = 0
    skipped_unparseable: int = 0
    skipped_unreadable: int = 0

    @property
    def complete(self) -> bool:
        return (
            self.unlink_failed == 0
            and self.skipped_unparseable == 0
            and self.skipped_unreadable == 0
        )


def _validate_optional_safe_id(v: str | None) -> str | None:
    if v is None:
        return v
    if not SAFE_ID.match(v):
        raise ValueError(f"Invalid project_id: {v!r}")
    return v


class ConversationRecord(BaseModel):
    """Full conversation stored as a single JSON file."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    messages: list[Message] = Field(default_factory=list)
    project_id: str | None = None

    validate_project_id = field_validator("project_id")(_validate_optional_safe_id)


class ConversationSummary(BaseModel):
    """Lightweight metadata for sidebar listing."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str
    created_at: str
    updated_at: str
    message_count: int = Field(ge=0)
    project_id: str | None = None

    validate_project_id = field_validator("project_id")(_validate_optional_safe_id)


class ConversationStore:
    """File-backed conversation persistence. One JSON file per conversation."""

    def __init__(self, config: PersistenceConfig) -> None:
        self._base_dir = Path(config.data_dir).expanduser().resolve()
        self._conv_dir = self._base_dir / "conversations"
        self._pending_tasks: set[asyncio.Task] = set()

    def ensure_dirs(self) -> None:
        """Create data directories. Call once at startup."""
        self._conv_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> Path:
        if not SAFE_ID.match(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return self._conv_dir / f"{session_id}.json"

    def save_sync(
        self,
        session_id: str,
        messages: list[Message],
        project_id: str | None = None,
    ) -> None:
        """Save conversation atomically via tempfile + os.replace."""
        record = ConversationRecord(
            id=session_id,
            title=_derive_title(messages),
            messages=messages,
            updated_at=datetime.now(timezone.utc).isoformat(),
            project_id=project_id,
        )

        path = self._path_for(session_id)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                record.created_at = existing.get("created_at", record.created_at)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Could not read existing created_at for %s, using current time: %s",
                    session_id,
                    e,
                )

        data = record.model_dump_json(indent=2)
        fd = -1
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self._conv_dir, suffix=".tmp", prefix=f".{session_id}_"
            )
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp_path, path)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    async def save(
        self,
        session_id: str,
        messages: list[Message],
        project_id: str | None = None,
    ) -> None:
        """Async save via thread pool."""
        await asyncio.to_thread(self.save_sync, session_id, messages, project_id)

    def save_background(
        self,
        session_id: str,
        messages: list[Message],
        project_id: str | None = None,
    ) -> None:
        """Fire-and-forget save. Logs errors instead of raising."""
        snapshot = list(messages)

        async def _do_save() -> None:
            try:
                await self.save(session_id, snapshot, project_id)
            except Exception:
                logger.exception(
                    "Failed to save conversation %s", session_id
                )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_save())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            try:
                self.save_sync(session_id, snapshot, project_id)
            except Exception:
                logger.exception(
                    "Failed to save conversation %s (sync fallback)", session_id
                )

    def load(self, session_id: str) -> ConversationRecord | None:
        """Load a conversation by ID. Returns None if not found or corrupt."""
        path = self._path_for(session_id)
        if not path.exists():
            return None
        try:
            data = path.read_text(encoding="utf-8")
            return ConversationRecord.model_validate_json(data)
        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning(
                "Failed to load conversation %s", session_id, exc_info=True
            )
            return None

    def list_conversations(
        self, project_id: str | None = None
    ) -> list[ConversationSummary]:
        """List saved conversations, sorted by updated_at descending.

        When ``project_id`` is provided, return only conversations with a
        matching ``project_id``. ``None`` returns all conversations regardless
        of their project assignment.
        """
        summaries: list[ConversationSummary] = []
        if not self._conv_dir.exists():
            return summaries

        for path in self._conv_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record_project_id = data.get("project_id")
                if project_id is not None and record_project_id != project_id:
                    continue
                summaries.append(
                    ConversationSummary(
                        id=data["id"],
                        title=data.get("title", ""),
                        created_at=data.get("created_at", ""),
                        updated_at=data.get("updated_at", ""),
                        message_count=len(data.get("messages", [])),
                        project_id=record_project_id,
                    )
                )
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                logger.warning(
                    "Skipping unreadable conversation file: %s",
                    path.name,
                    exc_info=True,
                )

        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    async def load_async(self, session_id: str) -> ConversationRecord | None:
        """Async variant of load via thread pool."""
        return await asyncio.to_thread(self.load, session_id)

    async def list_conversations_async(
        self, project_id: str | None = None
    ) -> list[ConversationSummary]:
        """Async variant of list_conversations via thread pool."""
        return await asyncio.to_thread(self.list_conversations, project_id)

    def delete(self, session_id: str) -> bool:
        """Delete a conversation file. Returns True if deleted."""
        path = self._path_for(session_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            logger.warning(
                "Failed to delete conversation %s", session_id, exc_info=True
            )
            return False

    def delete_by_project(self, project_id: str) -> DeleteByProjectResult:
        """Delete every conversation tied to ``project_id``.

        Returns a :class:`DeleteByProjectResult` with per-category counts so
        callers can decide whether the cascade is complete enough to continue
        with a project-record delete.

        - ``deleted``: files this process unlinked successfully.
        - ``unlink_failed``: files whose project assignment matched but whose
          ``unlink`` raised :class:`OSError` (permissions, busy, etc.). The
          file likely still exists; logged at ERROR.
        - ``skipped_unparseable``: files that could not be JSON-decoded.
          Project assignment is unknowable; the file is left on disk.
        - ``skipped_unreadable``: files that raised :class:`OSError` on
          read. Project assignment is unknowable; the file is left on disk
          and logged at ERROR.

        A concurrent removal of a matching file between scan and unlink is
        treated as success-by-proxy (the file is gone, which is what the
        caller asked for) — it is NOT counted in ``deleted`` and does NOT
        increment ``unlink_failed``; ``complete`` remains ``True`` in that
        case.
        """
        if not self._conv_dir.exists():
            return DeleteByProjectResult()

        result = DeleteByProjectResult()
        for path in self._conv_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning(
                    "Skipping unparseable conversation file during project delete: %s",
                    path.name,
                    exc_info=True,
                )
                result = replace(
                    result, skipped_unparseable=result.skipped_unparseable + 1
                )
                continue
            except OSError:
                logger.error(
                    "Unreadable conversation file during project delete: %s",
                    path.name,
                    exc_info=True,
                )
                result = replace(
                    result, skipped_unreadable=result.skipped_unreadable + 1
                )
                continue
            if data.get("project_id") != project_id:
                continue
            try:
                path.unlink()
                result = replace(result, deleted=result.deleted + 1)
            except FileNotFoundError:
                continue
            except OSError:
                logger.error(
                    "Failed to unlink conversation %s during project delete",
                    path.name,
                    exc_info=True,
                )
                result = replace(result, unlink_failed=result.unlink_failed + 1)
        return result

    async def delete_by_project_async(
        self, project_id: str
    ) -> DeleteByProjectResult:
        """Async variant of delete_by_project via thread pool."""
        return await asyncio.to_thread(self.delete_by_project, project_id)


def _derive_title(messages: list[Message]) -> str:
    """Extract title from first user message, truncated to 80 chars."""
    for msg in messages:
        if msg.role == "user" and msg.content:
            title = msg.content.strip().replace("\n", " ")
            return title[:80]
    return "Untitled"
