from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from stoiquent.cli import main


def test_should_call_start_with_loaded_config() -> None:
    runner = CliRunner()
    with patch("stoiquent.config.load_config") as mock_load, \
         patch("stoiquent.app.start") as mock_start:
        mock_load.return_value = MagicMock()
        runner.invoke(main, ["run"])

    mock_start.assert_called_once()


def test_should_override_mode_to_browser() -> None:
    runner = CliRunner()
    with patch("stoiquent.config.load_config") as mock_load, \
         patch("stoiquent.app.start") as mock_start:
        config = MagicMock()
        config.ui.host = "127.0.0.1"
        config.ui.port = 8080
        mock_load.return_value = config
        runner.invoke(main, ["run", "--mode", "browser"])

    called_config = mock_start.call_args[0][0]
    assert called_config.ui.mode == "browser"


def test_should_override_mode_to_native() -> None:
    runner = CliRunner()
    with patch("stoiquent.config.load_config") as mock_load, \
         patch("stoiquent.app.start") as mock_start:
        config = MagicMock()
        config.ui.host = "127.0.0.1"
        config.ui.port = 8080
        mock_load.return_value = config
        runner.invoke(main, ["run", "--mode", "native"])

    called_config = mock_start.call_args[0][0]
    assert called_config.ui.mode == "native"
