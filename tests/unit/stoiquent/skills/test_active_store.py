from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.models import PersistenceConfig
from stoiquent.skills.active_store import (
    ActiveSkillsLoadError,
    ActiveSkillsRecord,
    ActiveSkillsStore,
)


def _make_store(tmp_path: Path) -> ActiveSkillsStore:
    return ActiveSkillsStore(PersistenceConfig(data_dir=str(tmp_path)))


def test_should_return_empty_list_when_file_absent(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.load() == []


def test_should_save_and_reload_active_names(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(["gh-cli", "hello-world"])
    assert store.load() == ["gh-cli", "hello-world"]


def test_should_sort_and_deduplicate_on_save(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(["zebra", "alpha", "alpha"])
    assert store.load() == ["alpha", "zebra"]


def test_should_overwrite_existing_record(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(["first"])
    store.save_sync(["second", "third"])
    assert store.load() == ["second", "third"]


def test_should_raise_load_error_on_damaged_json(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ActiveSkillsLoadError):
        store.load()


def test_should_raise_load_error_on_schema_invalid_payload(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"active": "not-a-list"}', encoding="utf-8")
    with pytest.raises(ActiveSkillsLoadError):
        store.load()


def test_should_create_base_dir_on_save(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "does-not-exist"
    store = ActiveSkillsStore(PersistenceConfig(data_dir=str(nested)))
    store.save_sync(["gh-cli"])
    assert (nested / "active_skills.json").exists()


def test_should_expose_record_with_iso_timestamp(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_sync(["gh-cli"])
    raw = store.path.read_text(encoding="utf-8")
    record = ActiveSkillsRecord.model_validate_json(raw)
    assert record.updated_at.endswith("+00:00")


async def test_should_save_async_without_blocking(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    await store.save(["async-one"])
    assert await store.load_async() == ["async-one"]


async def test_save_background_snapshots_input(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    names = ["a", "b"]
    store.save_background(names)
    names.append("c")
    await store.drain_pending()
    assert store.load() == ["a", "b"]


async def test_save_background_errors_are_logged_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)

    def _boom(_: list[str]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_sync", _boom)
    store.save_background(["x"])
    await store.drain_pending()


def test_save_background_uses_sync_fallback_without_event_loop(
    tmp_path: Path,
) -> None:
    store = _make_store(tmp_path)
    store.save_background(["sync-fallback"])
    assert store.load() == ["sync-fallback"]


async def test_drain_pending_is_noop_when_no_pending_tasks(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    await store.drain_pending()


async def test_drain_pending_awaits_all_in_flight_tasks(
    tmp_path: Path,
) -> None:
    store = _make_store(tmp_path)
    store.save_background(["one"])
    store.save_background(["one", "two"])
    await store.drain_pending()
    assert store._pending_tasks == set()  # noqa: SLF001


async def test_save_background_preserves_fifo_order(tmp_path: Path) -> None:
    """Rapid concurrent save_background calls must land in call order;
    the last-scheduled state wins. Without the internal save lock, two
    os.replace calls race and the on-disk state is non-deterministic."""
    store = _make_store(tmp_path)
    store.save_background(["a"])
    store.save_background(["a", "b"])
    store.save_background(["a", "b", "c"])
    await store.drain_pending()
    assert store.load() == ["a", "b", "c"]


def test_path_property_points_at_active_skills_json(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.path.name == "active_skills.json"
    assert store.path.parent == tmp_path.resolve()


def test_ensure_dirs_creates_base_directory(tmp_path: Path) -> None:
    target = tmp_path / "stoiquent-home"
    store = ActiveSkillsStore(PersistenceConfig(data_dir=str(target)))
    store.ensure_dirs()
    assert target.exists()


async def test_should_return_empty_list_when_file_vanishes_between_exists_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)
    store.save_sync(["temp"])

    original_read = Path.read_text

    def _vanishing_read(self: Path, *args: object, **kwargs: object) -> str:
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "read_text", _vanishing_read)
    assert store.load() == []
    monkeypatch.setattr(Path, "read_text", original_read)
