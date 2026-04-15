from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from stoiquent.models import Message, PersistenceConfig

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


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


class ConversationSummary(BaseModel):
    """Lightweight metadata for sidebar listing."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str
    created_at: str
    updated_at: str
    message_count: int = Field(ge=0)


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
        if not _SAFE_ID.match(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return self._conv_dir / f"{session_id}.json"

    def save_sync(self, session_id: str, messages: list[Message]) -> None:
        """Save conversation atomically via tempfile + os.replace."""
        record = ConversationRecord(
            id=session_id,
            title=_derive_title(messages),
            messages=messages,
            updated_at=datetime.now(timezone.utc).isoformat(),
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

    async def save(self, session_id: str, messages: list[Message]) -> None:
        """Async save via thread pool."""
        await asyncio.to_thread(self.save_sync, session_id, messages)

    def save_background(self, session_id: str, messages: list[Message]) -> None:
        """Fire-and-forget save. Logs errors instead of raising."""
        snapshot = list(messages)

        async def _do_save() -> None:
            try:
                await self.save(session_id, snapshot)
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
                self.save_sync(session_id, snapshot)
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

    def list_conversations(self) -> list[ConversationSummary]:
        """List all saved conversations, sorted by updated_at descending."""
        summaries: list[ConversationSummary] = []
        if not self._conv_dir.exists():
            return summaries

        for path in self._conv_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                summaries.append(
                    ConversationSummary(
                        id=data["id"],
                        title=data.get("title", ""),
                        created_at=data.get("created_at", ""),
                        updated_at=data.get("updated_at", ""),
                        message_count=len(data.get("messages", [])),
                    )
                )
            except (json.JSONDecodeError, OSError, KeyError):
                logger.warning(
                    "Skipping unreadable conversation file: %s",
                    path.name,
                    exc_info=True,
                )

        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    async def list_conversations_async(self) -> list[ConversationSummary]:
        """Async variant of list_conversations via thread pool."""
        return await asyncio.to_thread(self.list_conversations)

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


def _derive_title(messages: list[Message]) -> str:
    """Extract title from first user message, truncated to 80 chars."""
    for msg in messages:
        if msg.role == "user" and msg.content:
            title = msg.content.strip().replace("\n", " ")
            return title[:80]
    return "Untitled"
