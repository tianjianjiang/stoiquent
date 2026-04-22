from __future__ import annotations

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


# --- ConversationStore: project_id ---


def test_save_with_project_id_roundtrips(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("conv1", _sample_messages(), project_id="proj_alpha")

    record = store.load("conv1")
    assert record is not None
    assert record.project_id == "proj_alpha"


def test_load_legacy_conversation_without_project_id(tmp_path: Path) -> None:
    """Backward compatibility: records missing the project_id field load cleanly."""
    store = _make_store(tmp_path)
    legacy_path = tmp_path / "conversations" / "legacy.json"
    legacy_path.write_text(
        json.dumps(
            {
                "id": "legacy",
                "title": "Old",
                "created_at": "2026-04-01T00:00:00+00:00",
                "updated_at": "2026-04-01T00:00:00+00:00",
                "messages": [],
            }
        ),
        encoding="utf-8",
    )

    record = store.load("legacy")
    assert record is not None
    assert record.id == "legacy"
    assert record.project_id is None


def test_list_conversations_filtered_by_project(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("a", _sample_messages(), project_id="p1")
    store.save_sync("b", _sample_messages(), project_id="p2")
    store.save_sync("c", _sample_messages(), project_id="p1")
    store.save_sync("d", _sample_messages())  # no project

    summaries = store.list_conversations(project_id="p1")
    ids = sorted(s.id for s in summaries)
    assert ids == ["a", "c"]
    assert all(s.project_id == "p1" for s in summaries)


def test_list_conversations_unfiltered_returns_all(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("a", _sample_messages(), project_id="p1")
    store.save_sync("b", _sample_messages())

    summaries = store.list_conversations()
    ids = sorted(s.id for s in summaries)
    assert ids == ["a", "b"]


async def test_save_background_preserves_project_id(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_background("bg1", _sample_messages(), project_id="p1")
    await store.drain_pending()

    record = store.load("bg1")
    assert record is not None
    assert record.project_id == "p1"


async def test_save_background_preserves_none_project_id(tmp_path: Path) -> None:
    """Non-None session.project_id must round-trip; None remains None."""
    store = _make_store(tmp_path)
    store.save_background("bg_none", _sample_messages())
    await store.drain_pending()

    record = store.load("bg_none")
    assert record is not None
    assert record.project_id is None


async def test_save_background_logs_and_does_not_raise_on_async_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_store(tmp_path)

    def _raise(
        _session_id: str,
        _messages: list[Message],
        _project_id: str | None = None,
    ) -> None:
        raise OSError("simulated save failure")

    monkeypatch.setattr(store, "save_sync", _raise)

    with caplog.at_level("ERROR", logger="stoiquent.persistence"):
        store.save_background("bg_fail", _sample_messages())
        await store.drain_pending()

    assert any(
        "Failed to save conversation bg_fail" in r.message for r in caplog.records
    )


def test_save_background_logs_on_sync_fallback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_store(tmp_path)

    def _raise(
        _session_id: str,
        _messages: list[Message],
        _project_id: str | None = None,
    ) -> None:
        raise OSError("simulated save failure")

    monkeypatch.setattr(store, "save_sync", _raise)

    with caplog.at_level("ERROR", logger="stoiquent.persistence"):
        store.save_background("bg_sync_fail", _sample_messages())

    assert any(
        "sync fallback" in r.message and "bg_sync_fail" in r.message
        for r in caplog.records
    )


async def test_list_conversations_async_filters_by_project(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("a", _sample_messages(), project_id="p1")
    store.save_sync("b", _sample_messages(), project_id="p2")

    summaries = await store.list_conversations_async(project_id="p1")
    assert [s.id for s in summaries] == ["a"]


def test_list_conversations_empty_string_project_id_matches_nothing(tmp_path: Path) -> None:
    """Empty string is not a synonym for None. The validator rejects "" on save,
    so no persisted record can carry project_id=="" — filtering by "" returns [].
    Callers must pass None to disable filtering.
    """
    store = _make_store(tmp_path)
    store.save_sync("a", _sample_messages(), project_id="p1")
    store.save_sync("b", _sample_messages())

    summaries = store.list_conversations(project_id="")
    assert summaries == []


def test_save_with_invalid_project_id_rejected(tmp_path: Path) -> None:
    """SAFE_ID regex rejects path-traversal / shell-hazard project_ids."""
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="Invalid project_id"):
        store.save_sync("c1", _sample_messages(), project_id="../etc/passwd")


def test_list_conversations_skips_file_with_invalid_project_id(tmp_path: Path) -> None:
    """A hand-edited file with malformed project_id must not crash the listing."""
    store = _make_store(tmp_path)
    store.save_sync("good", _sample_messages(), project_id="p1")

    tampered_path = tmp_path / "conversations" / "bad.json"
    tampered_path.write_text(
        json.dumps(
            {
                "id": "bad",
                "title": "tampered",
                "created_at": "2026-04-17T00:00:00+00:00",
                "updated_at": "2026-04-17T00:00:00+00:00",
                "messages": [],
                "project_id": "../etc",
            }
        ),
        encoding="utf-8",
    )

    summaries = store.list_conversations()
    assert [s.id for s in summaries] == ["good"]


# --- ConversationStore: delete ---


def test_delete_removes_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("abc123", _sample_messages())

    assert store.delete("abc123") is True
    assert not (tmp_path / "conversations" / "abc123.json").exists()


def test_delete_returns_false_for_missing(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.delete("nonexistent") is False


# --- ConversationStore: delete_by_project ---


def test_delete_by_project_removes_matching(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("a1", _sample_messages(), project_id="proj1")
    store.save_sync("a2", _sample_messages(), project_id="proj1")
    store.save_sync("b1", _sample_messages(), project_id="proj2")

    result = store.delete_by_project("proj1")

    assert result.deleted == 2
    assert result.complete is True
    assert {s.id for s in store.list_conversations()} == {"b1"}


def test_delete_by_project_leaves_unrelated_intact(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("keep1", _sample_messages(), project_id="other")
    store.save_sync("keep2", _sample_messages(), project_id=None)

    result = store.delete_by_project("proj1")

    assert result.deleted == 0
    assert result.complete is True
    assert {s.id for s in store.list_conversations()} == {"keep1", "keep2"}


def test_delete_by_project_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    # ensure_dirs not called
    result = store.delete_by_project("proj1")
    assert result.deleted == 0
    assert result.complete is True


def test_delete_by_project_skips_corrupt_files(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("good", _sample_messages(), project_id="proj1")
    (tmp_path / "conversations" / "bad.json").write_text("{not json", encoding="utf-8")

    result = store.delete_by_project("proj1")
    assert result.deleted == 1
    assert result.skipped_unparseable == 1
    assert result.complete is False
    # Corrupt file is left alone (assignment is unknowable).
    assert (tmp_path / "conversations" / "bad.json").exists()


def test_delete_by_project_records_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-file OSError on unlink must surface in the result so the
    caller can decide whether to proceed with the project-record delete."""
    store = _make_store(tmp_path)
    store.save_sync("a1", _sample_messages(), project_id="proj1")
    store.save_sync("a2", _sample_messages(), project_id="proj1")

    real_unlink = Path.unlink
    target_name = "a1.json"

    def flaky_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == target_name:
            raise PermissionError("read-only FS")
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    result = store.delete_by_project("proj1")

    assert result.deleted == 1
    assert result.unlink_failed == 1
    assert result.complete is False
    remaining = {p.name for p in (tmp_path / "conversations").glob("*.json")}
    assert target_name in remaining


def test_delete_by_project_records_read_osError(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError on read (e.g., permission denied) is distinguished from
    JSON corruption so we can log at ERROR and surface it to the user."""
    store = _make_store(tmp_path)
    store.save_sync("a1", _sample_messages(), project_id="proj1")

    real_read = Path.read_text

    def flaky_read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "a1.json":
            raise PermissionError("denied")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read)

    result = store.delete_by_project("proj1")
    assert result.deleted == 0
    assert result.skipped_unreadable == 1
    assert result.complete is False
    # File is still on disk; unreadable is NOT permission to delete.
    assert (tmp_path / "conversations" / "a1.json").exists()


def test_delete_by_project_silent_no_op_on_unsafe_id(tmp_path: Path) -> None:
    """Locks current behavior: delete_by_project does not validate the id;
    unsafe values match nothing rather than raising. If future work moves
    to raising, update this test rather than changing the behavior silently.
    """
    store = _make_store(tmp_path)
    store.save_sync("keep", _sample_messages(), project_id="proj1")

    assert store.delete_by_project("").complete is True
    assert store.delete_by_project("../etc").deleted == 0
    assert {s.id for s in store.list_conversations()} == {"keep"}


def test_delete_by_project_fnfe_on_read_is_success_by_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A race between ``glob`` and ``read_text`` must be treated the
    same as the unlink-side race: success-by-proxy, not an unreadable
    failure that aborts the cascade."""
    store = _make_store(tmp_path)
    store.save_sync("a1", _sample_messages(), project_id="proj1")
    store.save_sync("a2", _sample_messages(), project_id="proj1")

    real_read = Path.read_text
    raced_name = "a1.json"

    def racing_read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == raced_name:
            raise FileNotFoundError("raced away")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", racing_read)

    result = store.delete_by_project("proj1")

    assert result.deleted == 1
    assert result.skipped_unreadable == 0
    assert result.complete is True


def test_delete_by_project_unicode_decode_error_is_unparseable(
    tmp_path: Path
) -> None:
    """Non-UTF-8 bytes on disk cannot reveal a project_id; count as
    unparseable so the caller sees `complete=False` and aborts."""
    store = _make_store(tmp_path)
    store.save_sync("good", _sample_messages(), project_id="proj1")
    (tmp_path / "conversations" / "bad.json").write_bytes(b"\xff\xfe\x00not utf8")

    result = store.delete_by_project("proj1")

    assert result.deleted == 1
    assert result.skipped_unparseable == 1
    assert result.complete is False


def test_delete_by_project_non_object_payload_is_unparseable(
    tmp_path: Path
) -> None:
    """Valid JSON that isn't a dict cannot carry a project_id and
    must not raise AttributeError inside the loop."""
    store = _make_store(tmp_path)
    store.save_sync("good", _sample_messages(), project_id="proj1")
    (tmp_path / "conversations" / "scalar.json").write_text("42", encoding="utf-8")
    (tmp_path / "conversations" / "list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "conversations" / "null.json").write_text("null", encoding="utf-8")

    result = store.delete_by_project("proj1")

    assert result.deleted == 1
    assert result.skipped_unparseable == 3
    assert result.complete is False


def test_delete_by_project_fnfe_is_success_by_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent removal between scan and unlink is treated as success-
    by-proxy: it does NOT count in ``deleted`` nor in ``unlink_failed``
    and leaves ``complete`` True."""
    store = _make_store(tmp_path)
    store.save_sync("a1", _sample_messages(), project_id="proj1")
    store.save_sync("a2", _sample_messages(), project_id="proj1")

    real_unlink = Path.unlink
    raced_name = "a1.json"

    def racing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == raced_name:
            raise FileNotFoundError("raced away")
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", racing_unlink)

    result = store.delete_by_project("proj1")

    assert result.deleted == 1
    assert result.unlink_failed == 0
    assert result.complete is True


async def test_delete_by_project_async_removes_matching(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync("a1", _sample_messages(), project_id="proj1")
    store.save_sync("b1", _sample_messages(), project_id="proj2")

    result = await store.delete_by_project_async("proj1")

    assert result.deleted == 1
    assert result.complete is True
    assert {s.id for s in store.list_conversations()} == {"b1"}


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
    await store.drain_pending()

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
