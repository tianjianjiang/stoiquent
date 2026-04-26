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
    the last-scheduled state wins. Without the internal save lock,
    multiple os.replace calls race and the on-disk state is
    non-deterministic."""
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


def test_quarantine_damaged_renames_file_with_iso_timestamp_suffix(
    tmp_path: Path,
) -> None:
    """A damaged file is moved aside under a sidecar name that (a)
    preserves the original contents for manual inspection and (b)
    contains a timestamp so multiple damage events don't collide."""
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("corrupt bytes", encoding="utf-8")

    sidecar = store.quarantine_damaged()
    assert sidecar is not None
    assert not store.path.exists()
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8") == "corrupt bytes"
    assert sidecar.name.startswith("active_skills.json.corrupt-")
    assert sidecar.name.endswith("Z"), (
        "sidecar suffix should be an ISO-8601 timestamp ending with Z"
    )


def test_quarantine_damaged_returns_none_when_file_missing(
    tmp_path: Path,
) -> None:
    """Guard against callers invoking quarantine on an already-absent
    file (e.g. a racing external process cleaned it up between load and
    quarantine). Must be a silent no-op, not a raise."""
    store = _make_store(tmp_path)
    assert store.quarantine_damaged() is None


def test_quarantine_damaged_uses_numeric_suffix_on_subsecond_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two damage events within the same wall-clock second must not
    silently clobber each other — ``os.replace`` atomically overwrites
    the destination, so a second sidecar at the same path would silently
    overwrite the first sidecar's contents and leave only the latest
    corrupt snapshot. The docstring promises both snapshots survive."""
    from datetime import datetime, timezone

    from stoiquent.skills import active_store as module

    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("first damage", encoding="utf-8")

    fixed = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedClock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return fixed

    monkeypatch.setattr(module, "datetime", _FixedClock)

    first = store.quarantine_damaged()
    assert first is not None and first.exists()
    assert first.read_text(encoding="utf-8") == "first damage"

    store.path.write_text("second damage", encoding="utf-8")
    second = store.quarantine_damaged()

    assert second is not None and second.exists()
    assert second != first, "second sidecar must not collide with first"
    assert first.exists(), "first sidecar must survive a same-second collision"
    assert first.read_text(encoding="utf-8") == "first damage"
    assert second.read_text(encoding="utf-8") == "second damage"


def test_quarantine_damaged_returns_none_and_logs_on_rename_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the rename itself fails (read-only filesystem, permissions),
    return None and log rather than raise. Quarantine is a recovery
    path — it must never abort the startup sequence that invoked it."""
    import logging
    import os

    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("corrupt", encoding="utf-8")

    def _replace_raises(src: object, dst: object) -> None:
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _replace_raises)
    with caplog.at_level(logging.ERROR, logger="stoiquent.skills.active_store"):
        result = store.quarantine_damaged()
    assert result is None
    assert store.path.exists(), "original file must be left intact on failure"
    assert any(
        "Failed to quarantine" in r.getMessage() for r in caplog.records
    )
    caplog.clear()
