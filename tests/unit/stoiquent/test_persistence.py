from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from stoiquent.models import Message, PersistenceConfig
from stoiquent.persistence import (
    ConversationRecord,
    ConversationSummary,
    ConversationStore,
    _derive_title,
)


def _make_store(tmp_path: Path):
    """Create a ConversationStore pointing at tmp_path."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    store.ensure_dirs()
    return store


def _sample_messages() -> list[Message]:
    return [
        Message(role="user", content="Hello, world!"),
        Message(role="assistant", content="Hi there!"),
    ]


# --- ConversationStore: ensure_dirs ---


def test_ensure_dirs_creates_conversations_directory(tmp_path: Path) -> None:
    _make_store(tmp_path)
    assert (tmp_path / "conversations").is_dir()


# --- ConversationStore: save_sync ---


def test_save_sync_creates_json_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc123", _sample_messages())

    path = tmp_path / "conversations" / "abc123.json"
    assert path.exists()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "abc123"
    assert data["title"] == "Hello, world!"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


def test_save_sync_preserves_created_at_on_update(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc123", _sample_messages())

    path = tmp_path / "conversations" / "abc123.json"
    first_data = json.loads(path.read_text(encoding="utf-8"))
    original_created = first_data["created_at"]

    time.sleep(0.01)

    more_messages = [*_sample_messages(), Message(role="user", content="Another question")]
    store.save_sync("abc123", more_messages)

    second_data = json.loads(path.read_text(encoding="utf-8"))
    assert second_data["created_at"] == original_created
    assert second_data["updated_at"] >= original_created
    assert len(second_data["messages"]) == 3


def test_save_sync_atomic_no_tmp_files_remain(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc123", _sample_messages())

    conv_dir = tmp_path / "conversations"
    tmp_files = list(conv_dir.glob("*.tmp"))
    assert tmp_files == []


# --- ConversationStore: load ---


def test_load_returns_conversation_record(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc123", _sample_messages())

    record = store.load("abc123")
    assert record is not None
    assert isinstance(record, ConversationRecord)
    assert record.id == "abc123"
    assert record.title == "Hello, world!"
    assert len(record.messages) == 2


def test_load_returns_none_for_missing_id(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.load("nonexistent") is None


def test_load_returns_none_for_corrupt_json(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    corrupt_path = tmp_path / "conversations" / "bad.json"
    corrupt_path.write_text("{invalid json", encoding="utf-8")

    assert store.load("bad") is None


# --- ConversationStore: list_conversations ---


def test_list_conversations_sorted_by_updated_at(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    store.save_sync("first", [Message(role="user", content="First")])
    time.sleep(0.01)
    store.save_sync("second", [Message(role="user", content="Second")])
    time.sleep(0.01)
    store.save_sync("third", [Message(role="user", content="Third")])

    summaries = store.list_conversations()
    assert len(summaries) == 3
    assert summaries[0].id == "third"
    assert summaries[1].id == "second"
    assert summaries[2].id == "first"


def test_list_conversations_empty_when_no_files(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.list_conversations() == []


def test_list_conversations_skips_corrupt_files(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("good", _sample_messages())

    corrupt_path = tmp_path / "conversations" / "bad.json"
    corrupt_path.write_text("not json", encoding="utf-8")

    summaries = store.list_conversations()
    assert len(summaries) == 1
    assert summaries[0].id == "good"


# --- ConversationStore: delete ---


def test_delete_removes_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc123", _sample_messages())

    assert store.delete("abc123") is True
    assert not (tmp_path / "conversations" / "abc123.json").exists()


def test_delete_returns_false_for_missing(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.delete("nonexistent") is False


# --- ConversationStore: path traversal ---


def test_path_for_rejects_path_traversal(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="Invalid session_id"):
        store.save_sync("../../etc/passwd", _sample_messages())


def test_path_for_rejects_slashes(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="Invalid session_id"):
        store.load("foo/bar")


def test_path_for_accepts_valid_ids(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc-123_DEF", _sample_messages())
    assert store.load("abc-123_DEF") is not None


# --- _derive_title ---


def test_derive_title_from_first_user_message() -> None:
    messages = [
        Message(role="system", content="You are helpful"),
        Message(role="user", content="What is Python?"),
        Message(role="assistant", content="A programming language"),
    ]
    assert _derive_title(messages) == "What is Python?"


def test_derive_title_truncates_at_80_chars() -> None:
    long_text = "x" * 120
    messages = [Message(role="user", content=long_text)]
    title = _derive_title(messages)
    assert len(title) == 80
    assert title == "x" * 80


def test_derive_title_returns_untitled_for_no_user_message() -> None:
    messages = [Message(role="system", content="System prompt")]
    assert _derive_title(messages) == "Untitled"

    assert _derive_title([]) == "Untitled"


# --- Async save ---


async def test_save_async_writes_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    await store.save("async123", _sample_messages())

    path = tmp_path / "conversations" / "async123.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "async123"


async def test_list_conversations_async(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("a1", [Message(role="user", content="Alpha")])
    store.save_sync("b2", [Message(role="user", content="Beta")])

    summaries = await store.list_conversations_async()
    assert len(summaries) == 2


async def test_save_background_completes_without_error(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_background("bg123", _sample_messages())

    # Give the background task time to complete
    await asyncio.sleep(0.1)

    path = tmp_path / "conversations" / "bg123.json"
    assert path.exists()


# --- Model round-trip ---


def test_conversation_record_serialization_round_trip() -> None:
    record = ConversationRecord(
        id="test123",
        title="Test conversation",
        messages=_sample_messages(),
    )
    json_str = record.model_dump_json()
    restored = ConversationRecord.model_validate_json(json_str)

    assert restored.id == record.id
    assert restored.title == record.title
    assert len(restored.messages) == len(record.messages)
    assert restored.messages[0].role == "user"
    assert restored.messages[0].content == "Hello, world!"


def test_conversation_summary_fields() -> None:
    summary = ConversationSummary(
        id="s1",
        title="My chat",
        created_at="2026-04-14T10:00:00+00:00",
        updated_at="2026-04-14T10:05:00+00:00",
        message_count=5,
    )
    assert summary.id == "s1"
    assert summary.title == "My chat"
    assert summary.message_count == 5
