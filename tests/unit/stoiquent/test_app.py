from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stoiquent.models import AppConfig, ProviderConfig, UIConfig


def test_should_raise_system_exit_when_provider_not_found() -> None:
    config = AppConfig(
        default_provider="nonexistent",
        providers={},
    )
    with patch("stoiquent.app.ui"):
        from stoiquent.app import start

        with pytest.raises(SystemExit, match="not found in config"):
            start(config)


def test_should_include_guidance_in_error_message() -> None:
    config = AppConfig(
        default_provider="nonexistent",
        providers={},
    )
    with patch("stoiquent.app.ui"):
        from stoiquent.app import start

        with pytest.raises(SystemExit, match="Check stoiquent.toml"):
            start(config)


def test_should_pass_native_kwargs_for_native_mode() -> None:
    config = AppConfig(
        ui=UIConfig(mode="native"),
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app"):
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)

        from stoiquent.app import start

        start(config)

        call_kwargs = mock_ui.run.call_args[1]
        assert call_kwargs["native"] is True
        assert call_kwargs["window_size"] == (1200, 800)
        assert "host" not in call_kwargs


def test_should_pass_browser_kwargs_for_browser_mode() -> None:
    config = AppConfig(
        ui=UIConfig(mode="browser", host="0.0.0.0", port=9000),
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app"):
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)

        from stoiquent.app import start

        start(config)

        call_kwargs = mock_ui.run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000
        assert "native" not in call_kwargs


def test_should_register_shutdown_hook() -> None:
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)

        from stoiquent.app import start

        start(config)

        assert mock_app.on_shutdown.call_count >= 1


def test_should_drain_pending_store_writes_on_shutdown() -> None:
    """Both stores' drain_pending must be registered on app.on_shutdown so that
    in-flight save_background tasks finish before NiceGUI tears the loop down.
    Without this, chat messages / project edits saved shortly before close can
    be lost.

    Store drains must be registered *after* provider.close and
    mcp_bridge.stop_all so any subsystem-triggered final writes have already
    been issued when we start awaiting the pending-tasks set.
    """
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.OpenAICompatProvider") as mock_provider_cls, \
         patch("stoiquent.app.MCPBridge") as mock_bridge_cls, \
         patch("stoiquent.app.ConversationStore") as mock_conv_store_cls, \
         patch("stoiquent.app.ProjectStore") as mock_project_store_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)

        from stoiquent.app import start

        start(config)

        registered = [call.args[0] for call in mock_app.on_shutdown.call_args_list]
        conv_drain = mock_conv_store_cls.return_value.drain_pending
        project_drain = mock_project_store_cls.return_value.drain_pending
        assert conv_drain in registered
        assert project_drain in registered

        provider_close_idx = registered.index(mock_provider_cls.return_value.close)
        bridge_stop_idx = registered.index(mock_bridge_cls.return_value.stop_all)
        conv_drain_idx = registered.index(conv_drain)
        project_drain_idx = registered.index(project_drain)
        assert provider_close_idx < conv_drain_idx
        assert bridge_stop_idx < conv_drain_idx
        assert conv_drain_idx < project_drain_idx


def test_should_raise_systemexit_when_project_store_ensure_dirs_fails() -> None:
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app"), \
         patch("stoiquent.app.ConversationStore") as mock_conv_store_cls, \
         patch("stoiquent.app.ProjectStore") as mock_project_store_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        # ConversationStore.ensure_dirs must succeed so the failure is pinned
        # to ProjectStore.ensure_dirs specifically.
        mock_conv_store_cls.return_value.ensure_dirs.return_value = None
        mock_project_store_cls.return_value.ensure_dirs.side_effect = OSError(
            "simulated project-store mkdir failure"
        )

        from stoiquent.app import start

        with pytest.raises(SystemExit, match="simulated project-store mkdir failure"):
            start(config)

        # Pins ordering: ConversationStore succeeds first; ProjectStore raises second.
        mock_conv_store_cls.return_value.ensure_dirs.assert_called_once()
        mock_project_store_cls.return_value.ensure_dirs.assert_called_once()


def test_should_register_active_store_drain_on_shutdown() -> None:
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)

        from stoiquent.app import start

        start(config)

        registered = [call.args[0] for call in mock_app.on_shutdown.call_args_list]
        assert mock_active_store_cls.return_value.drain_pending in registered


def test_should_register_restore_hook_on_startup() -> None:
    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)

        from stoiquent.app import start

        start(config)

        assert mock_app.on_startup.call_count == 1
        hook = mock_app.on_startup.call_args_list[0].args[0]
        assert hook.__name__ == "_restore_active_skills"


async def test_restore_activates_every_saved_skill() -> None:
    from unittest.mock import AsyncMock

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.return_value = ["hello", "gh-cli"]
        mock_controller_cls.return_value.activate_many = AsyncMock(return_value={})

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        await hook()
        mock_controller_cls.return_value.activate_many.assert_awaited_once_with(
            ["hello", "gh-cli"]
        )


async def test_restore_is_noop_when_active_store_damaged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from pathlib import Path
    from unittest.mock import AsyncMock

    from stoiquent.skills.active_store import ActiveSkillsLoadError

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls, \
         patch("stoiquent.app.Session") as mock_session_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.side_effect = ActiveSkillsLoadError(
            "damaged"
        )
        sidecar_path = Path("/tmp/active_skills.json.corrupt-20260424T000000Z")
        mock_active_store_cls.return_value.quarantine_damaged.return_value = (
            sidecar_path
        )
        mock_controller_cls.return_value.activate_many = AsyncMock()
        fake_warnings: list[str] = []
        mock_session_cls.return_value.startup_warnings = fake_warnings

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        with caplog.at_level("ERROR", logger="stoiquent.app"):
            await hook()

        mock_controller_cls.return_value.activate_many.assert_not_called()
        mock_active_store_cls.return_value.quarantine_damaged.assert_called_once_with()
        assert any(
            "active_skills.json is damaged" in r.getMessage()
            and r.exc_info is not None
            for r in caplog.records
        ), "damaged-JSON branch must emit logger.exception, not logger.warning"
        assert any(
            str(sidecar_path) in w and "damaged" in w for w in fake_warnings
        ), f"session.startup_warnings should name the sidecar; got {fake_warnings!r}"


async def test_restore_mirrors_user_warning_to_logger_for_headless_visibility(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The user-facing warning text is mirrored to ``logger.warning`` so
    headless or pre-mount exits (port-in-use, native-window crash) still
    leave the message on disk — the queued copy is only surfaced on the
    first page render, which never happens if the app exits before any
    layout build."""
    from pathlib import Path
    from unittest.mock import AsyncMock

    from stoiquent.skills.active_store import ActiveSkillsLoadError

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls, \
         patch("stoiquent.app.Session") as mock_session_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.side_effect = ActiveSkillsLoadError(
            "damaged"
        )
        sidecar_path = Path("/tmp/active_skills.json.corrupt-20260424T000000Z")
        mock_active_store_cls.return_value.quarantine_damaged.return_value = (
            sidecar_path
        )
        mock_controller_cls.return_value.activate_many = AsyncMock()
        fake_warnings: list[str] = []
        mock_session_cls.return_value.startup_warnings = fake_warnings

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        with caplog.at_level("WARNING", logger="stoiquent.app"):
            await hook()

        warning_records = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "Startup warning queued for user" in r.getMessage()
        ]
        assert warning_records, (
            "user-facing warning must be mirrored to logger.warning so"
            " headless/pre-mount exits still leave the message on disk"
        )
        assert str(sidecar_path) in warning_records[0].getMessage()
        assert "damaged" in warning_records[0].getMessage()
        caplog.clear()


async def test_restore_mirrors_fallback_warning_to_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Symmetric to the success-quarantine mirror test: the
    quarantine-failed branch's user-facing text is also mirrored."""
    from unittest.mock import AsyncMock

    from stoiquent.skills.active_store import ActiveSkillsLoadError

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls, \
         patch("stoiquent.app.Session") as mock_session_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.side_effect = ActiveSkillsLoadError(
            "damaged"
        )
        mock_active_store_cls.return_value.quarantine_damaged.return_value = None
        mock_controller_cls.return_value.activate_many = AsyncMock()
        fake_warnings: list[str] = []
        mock_session_cls.return_value.startup_warnings = fake_warnings

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        with caplog.at_level("WARNING", logger="stoiquent.app"):
            await hook()

        warning_records = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "Startup warning queued for user" in r.getMessage()
        ]
        assert warning_records, (
            "fallback warning must also be mirrored to logger.warning"
        )
        assert "could not be quarantined" in warning_records[0].getMessage()
        caplog.clear()


async def test_restore_appends_fallback_warning_when_quarantine_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """quarantine_damaged returns None when the rename itself fails
    (e.g. read-only fs). The startup path must still queue a warning —
    otherwise the user is left with a silently reset skill selection."""
    from unittest.mock import AsyncMock

    from stoiquent.skills.active_store import ActiveSkillsLoadError

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls, \
         patch("stoiquent.app.Session") as mock_session_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.side_effect = ActiveSkillsLoadError(
            "damaged"
        )
        mock_active_store_cls.return_value.quarantine_damaged.return_value = None
        mock_controller_cls.return_value.activate_many = AsyncMock()
        fake_warnings: list[str] = []
        mock_session_cls.return_value.startup_warnings = fake_warnings

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        with caplog.at_level("ERROR", logger="stoiquent.app"):
            await hook()

        assert len(fake_warnings) == 1
        assert "could not be quarantined" in fake_warnings[0]
        caplog.clear()


async def test_restore_logs_per_skill_activation_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import AsyncMock

    from stoiquent.skills.controller import ActivationResult

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.return_value = ["ghost-skill"]
        mock_controller_cls.return_value.activate_many = AsyncMock(
            return_value={
                "ghost-skill": ActivationResult(
                    success=False, reason="unknown-skill"
                )
            }
        )

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        with caplog.at_level("WARNING", logger="stoiquent.app"):
            await hook()
        assert any(
            "ghost-skill" in record.getMessage()
            and "unknown-skill" in record.getMessage()
            for record in caplog.records
        ), "per-skill failure should be logged with name and reason"


async def test_restore_swallows_unexpected_error_and_logs_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import AsyncMock

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.return_value = ["a"]
        mock_controller_cls.return_value.activate_many = AsyncMock(
            side_effect=RuntimeError("mcp-bridge-down")
        )

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        with caplog.at_level("ERROR", logger="stoiquent.app"):
            await hook()
        assert any(
            "Unhandled error restoring active skills" in record.getMessage()
            for record in caplog.records
        ), "broad except path should emit logger.exception"


async def test_restore_is_noop_when_no_persisted_skills() -> None:
    from unittest.mock import AsyncMock

    config = AppConfig(
        providers={"p": ProviderConfig(base_url="http://x", model="m")},
        default_provider="p",
    )
    with patch("stoiquent.app.ui") as mock_ui, \
         patch("stoiquent.app.app") as mock_app, \
         patch("stoiquent.app.ActiveSkillsStore") as mock_active_store_cls, \
         patch("stoiquent.app.SkillController") as mock_controller_cls:
        mock_ui.run = MagicMock()
        mock_ui.page = MagicMock(return_value=lambda f: f)
        mock_active_store_cls.return_value.load.return_value = []
        mock_controller_cls.return_value.activate_many = AsyncMock()

        from stoiquent.app import start

        start(config)

        hook = mock_app.on_startup.call_args_list[0].args[0]
        await hook()
        mock_controller_cls.return_value.activate_many.assert_not_called()
