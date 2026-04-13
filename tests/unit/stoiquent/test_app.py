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
         patch("stoiquent.app.app") as mock_app:
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
         patch("stoiquent.app.app") as mock_app:
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

        mock_app.on_shutdown.assert_called_once()
