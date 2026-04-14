from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from stoiquent.cli import main
from stoiquent.models import AppConfig, ProviderConfig


def _write_config(tmp_path: Path) -> Path:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("""\
[ui]
mode = "native"

[llm]
default = "test"

[llm.providers.test]
type = "openai"
base_url = "http://localhost:11434/v1"
model = "test"
""")
    return config_file


def test_should_call_start_with_loaded_config(
    tmp_path: Path, monkeypatch: object,
) -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    _write_config(tmp_path)
    mp.chdir(tmp_path)

    runner = CliRunner()
    with patch("stoiquent.app.start") as mock_start:
        runner.invoke(main, ["run"])

    mock_start.assert_called_once()
    mp.undo()


def test_should_override_mode_to_browser(
    tmp_path: Path, monkeypatch: object,
) -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    _write_config(tmp_path)
    mp.chdir(tmp_path)

    runner = CliRunner()
    with patch("stoiquent.app.start") as mock_start:
        runner.invoke(main, ["run", "--mode", "browser"])

    called_config = mock_start.call_args[0][0]
    assert called_config.ui.mode == "browser"
    mp.undo()


def test_should_override_mode_to_native(
    tmp_path: Path, monkeypatch: object,
) -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    _write_config(tmp_path)
    mp.chdir(tmp_path)

    runner = CliRunner()
    with patch("stoiquent.app.start") as mock_start:
        runner.invoke(main, ["run", "--mode", "native"])

    called_config = mock_start.call_args[0][0]
    assert called_config.ui.mode == "native"
    mp.undo()
