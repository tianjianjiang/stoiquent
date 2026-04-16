from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from stoiquent.models import PersistenceConfig
from stoiquent.projects import ProjectRecord, ProjectStore, ProjectSummary


def _make_store(tmp_path: Path) -> ProjectStore:
    """Create a ProjectStore pointing at tmp_path."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ProjectStore(config)
    store.ensure_dirs()
    return store


def _sample_project(**overrides: Any) -> ProjectRecord:
    defaults = {
        "id": "proj1",
        "name": "My Project",
        "folder": "/home/user/my-project",
        "instructions": "Use formal tone.",
    }
    defaults.update(overrides)
    return ProjectRecord(**defaults)


# --- ProjectStore: ensure_dirs ---


def test_ensure_dirs_creates_projects_directory(tmp_path: Path) -> None:
    _make_store(tmp_path)
    assert (tmp_path / "projects").is_dir()


# --- ProjectStore: save_sync ---


def test_save_sync_creates_json_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    path = tmp_path / "projects" / "proj1.json"
    assert path.exists()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "proj1"
    assert data["name"] == "My Project"
    assert data["folder"] == "/home/user/my-project"
    assert data["instructions"] == "Use formal tone."
    assert data["memory"] == {}


def test_save_sync_preserves_created_at_on_update(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    path = tmp_path / "projects" / "proj1.json"
    first_data = json.loads(path.read_text(encoding="utf-8"))
    original_created = first_data["created_at"]

    time.sleep(0.01)

    updated = _sample_project(instructions="Updated instructions")
    store.save_sync(updated)

    second_data = json.loads(path.read_text(encoding="utf-8"))
    assert second_data["created_at"] == original_created
    assert second_data["updated_at"] > first_data["updated_at"]
    assert second_data["instructions"] == "Updated instructions"


def test_save_sync_atomic_no_tmp_files_remain(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    projects_dir = tmp_path / "projects"
    # iterdir (not glob) matches dot-prefixed tempfiles from mkstemp.
    tmp_files = [p for p in projects_dir.iterdir() if p.name.endswith(".tmp")]
    assert tmp_files == []


def test_save_sync_cleans_up_tmp_on_os_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("stoiquent.projects.os.replace", _raise)

    with pytest.raises(OSError, match="simulated replace failure"):
        store.save_sync(_sample_project())

    projects_dir = tmp_path / "projects"
    remaining = [p for p in projects_dir.iterdir() if p.name.endswith(".tmp")]
    assert remaining == []


def test_save_sync_cleans_up_fd_on_os_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)

    def _raise(*_args: object, **_kwargs: object) -> int:
        raise OSError("simulated write failure")

    monkeypatch.setattr("stoiquent.projects.os.write", _raise)

    with pytest.raises(OSError, match="simulated write failure"):
        store.save_sync(_sample_project())

    projects_dir = tmp_path / "projects"
    remaining = [p for p in projects_dir.iterdir() if p.name.endswith(".tmp")]
    assert remaining == []


def test_save_sync_over_corrupt_existing_file(tmp_path: Path) -> None:
    """save_sync must recover when the target file is corrupt, not raise."""
    store = _make_store(tmp_path)
    corrupt_path = tmp_path / "projects" / "proj1.json"
    corrupt_path.write_text("{not valid json", encoding="utf-8")

    sample = _sample_project()
    store.save_sync(sample)

    loaded = store.load("proj1")
    assert loaded is not None
    assert loaded.id == "proj1"
    # created_at is taken from the caller (not carried over from corrupt file).
    assert loaded.created_at == sample.created_at


def test_save_sync_regenerates_created_at_when_existing_fails_schema(
    tmp_path: Path,
) -> None:
    """Valid JSON but schema-invalid existing file: created_at is not preserved."""
    store = _make_store(tmp_path)
    stale_path = tmp_path / "projects" / "proj1.json"
    # Valid JSON, but missing required 'name' field → load() returns None.
    stale_path.write_text(
        json.dumps(
            {
                "id": "proj1",
                "folder": "/f",
                "created_at": "2020-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    sample = _sample_project()
    store.save_sync(sample)

    loaded = store.load("proj1")
    assert loaded is not None
    assert loaded.created_at != "2020-01-01T00:00:00+00:00"
    assert loaded.created_at == sample.created_at


def test_save_sync_stores_memory(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    project = ProjectRecord(
        id="mem1",
        name="Memory Test",
        folder=str(tmp_path / "test"),
        memory={"key1": "value1", "key2": "value2"},
    )
    store.save_sync(project)

    loaded = store.load("mem1")
    assert loaded is not None
    assert loaded.memory == {"key1": "value1", "key2": "value2"}


# --- ProjectStore: load ---


def test_load_returns_project_record(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    record = store.load("proj1")
    assert record is not None
    assert isinstance(record, ProjectRecord)
    assert record.id == "proj1"
    assert record.name == "My Project"
    assert record.folder == "/home/user/my-project"
    assert record.instructions == "Use formal tone."


def test_load_returns_none_for_missing_id(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.load("nonexistent") is None


def test_load_returns_none_for_corrupt_json(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    corrupt_path = tmp_path / "projects" / "bad.json"
    corrupt_path.write_text("{invalid json", encoding="utf-8")

    assert store.load("bad") is None


# --- ProjectStore: list_projects ---


def test_list_projects_sorted_by_updated_at(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    store.save_sync(_sample_project(id="first", name="First"))
    time.sleep(0.01)
    store.save_sync(_sample_project(id="second", name="Second"))
    time.sleep(0.01)
    store.save_sync(_sample_project(id="third", name="Third"))

    summaries = store.list_projects()
    assert len(summaries) == 3
    assert summaries[0].id == "third"
    assert summaries[1].id == "second"
    assert summaries[2].id == "first"


def test_list_projects_empty_when_no_files(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.list_projects() == []


def test_list_projects_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    """list_projects must tolerate a store instantiated without ensure_dirs()."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ProjectStore(config)
    assert store.list_projects() == []


def test_list_projects_skips_corrupt_files(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    corrupt_path = tmp_path / "projects" / "bad.json"
    corrupt_path.write_text("not json", encoding="utf-8")

    summaries = store.list_projects()
    assert len(summaries) == 1
    assert summaries[0].id == "proj1"


def test_list_projects_skips_invalid_model_data(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    # Valid JSON but missing required 'name' field → ValidationError
    invalid_path = tmp_path / "projects" / "invalid.json"
    invalid_path.write_text(
        '{"id": "invalid", "folder": "/f"}', encoding="utf-8"
    )

    summaries = store.list_projects()
    assert len(summaries) == 1
    assert summaries[0].id == "proj1"


def test_list_projects_skips_id_filename_mismatch(tmp_path: Path) -> None:
    """Prevent spoofing: id inside JSON must match filename."""
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    spoofed_path = tmp_path / "projects" / "spoofed.json"
    spoofed_path.write_text(
        '{"id": "different", "name": "Spoof", "folder": "/x",'
        ' "instructions": "", "memory": {},'
        ' "created_at": "2026-04-16T00:00:00+00:00",'
        ' "updated_at": "2026-04-16T00:00:00+00:00"}',
        encoding="utf-8",
    )

    summaries = store.list_projects()
    assert len(summaries) == 1
    assert summaries[0].id == "proj1"


# --- ProjectStore: delete ---


def test_delete_removes_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    assert store.delete("proj1") is True
    assert not (tmp_path / "projects" / "proj1.json").exists()


def test_delete_returns_false_for_missing(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.delete("nonexistent") is False


def test_delete_returns_false_on_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """delete must swallow non-FileNotFoundError OSError and return False."""
    store = _make_store(tmp_path)
    store.save_sync(_sample_project())

    def _raise(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("simulated permission denied")

    monkeypatch.setattr(Path, "unlink", _raise)

    assert store.delete("proj1") is False


# --- ProjectStore: path traversal ---


def test_model_rejects_invalid_id() -> None:
    with pytest.raises(ValueError, match="Invalid project id"):
        _sample_project(id="../../etc/passwd")


def test_path_for_rejects_slashes(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="Invalid project_id"):
        store.load("foo/bar")


def test_path_for_accepts_valid_ids(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project(id="abc-123_DEF"))
    assert store.load("abc-123_DEF") is not None


# --- Async operations ---


async def test_save_async_writes_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    await store.save(_sample_project(id="async1"))

    path = tmp_path / "projects" / "async1.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "async1"


async def test_load_async_returns_project(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project(id="async_load"))

    record = await store.load_async("async_load")
    assert record is not None
    assert record.id == "async_load"
    assert record.name == "My Project"


async def test_list_projects_async(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(_sample_project(id="a1", name="Alpha"))
    store.save_sync(_sample_project(id="b2", name="Beta"))

    summaries = await store.list_projects_async()
    assert len(summaries) == 2


async def test_save_background_completes_without_error(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_background(_sample_project(id="bg1"))
    await store.drain_pending()

    path = tmp_path / "projects" / "bg1.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "bg1"
    assert data["name"] == "My Project"


async def test_save_background_logs_and_does_not_raise_on_async_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_store(tmp_path)

    def _raise(_project: ProjectRecord) -> None:
        raise OSError("simulated save failure")

    monkeypatch.setattr(store, "save_sync", _raise)

    with caplog.at_level("ERROR", logger="stoiquent.projects"):
        store.save_background(_sample_project(id="bg_fail"))
        await store.drain_pending()

    assert any("Failed to save project bg_fail" in r.message for r in caplog.records)


def test_save_background_logs_on_sync_fallback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_store(tmp_path)

    def _raise(_project: ProjectRecord) -> None:
        raise OSError("simulated save failure")

    monkeypatch.setattr(store, "save_sync", _raise)

    with caplog.at_level("ERROR", logger="stoiquent.projects"):
        store.save_background(_sample_project(id="bg_sync_fail"))

    assert any(
        "sync fallback" in r.message and "bg_sync_fail" in r.message
        for r in caplog.records
    )


def test_save_background_sync_fallback(tmp_path: Path) -> None:
    """save_background persists via save_sync when no event loop is running."""
    store = _make_store(tmp_path)
    store.save_background(_sample_project(id="sync_fb"))

    record = store.load("sync_fb")
    assert record is not None
    assert record.id == "sync_fb"


# --- Model round-trip ---


def test_project_record_serialization_round_trip() -> None:
    record = _sample_project()
    json_str = record.model_dump_json()
    restored = ProjectRecord.model_validate_json(json_str)

    assert restored.id == record.id
    assert restored.name == record.name
    assert restored.folder == record.folder
    assert restored.instructions == record.instructions
    assert restored.memory == record.memory
    assert restored.created_at == record.created_at
    assert restored.updated_at == record.updated_at


def test_project_summary_fields() -> None:
    summary = ProjectSummary(
        id="p1",
        name="Test Project",
        folder="/home/user/test",
        created_at="2026-04-16T10:00:00+00:00",
        updated_at="2026-04-16T10:05:00+00:00",
    )
    assert summary.id == "p1"
    assert summary.name == "Test Project"
    assert summary.folder == "/home/user/test"
    assert summary.created_at == "2026-04-16T10:00:00+00:00"
    assert summary.updated_at == "2026-04-16T10:05:00+00:00"
