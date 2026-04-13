from __future__ import annotations

import os

import pytest

from stoiquent.config import load_config


@pytest.mark.integration
def test_should_load_project_stoiquent_toml() -> None:
    """Verify stoiquent.toml in project root loads correctly."""
    original_cwd = os.getcwd()
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    try:
        os.chdir(project_root)
        config = load_config()
        assert config.default_provider == "local-qwen"
        assert "local-qwen" in config.providers
        assert config.providers["local-qwen"].model == "qwen3:32b"
        assert config.providers["local-qwen"].supports_reasoning is True
        assert config.ui.mode == "native"
    finally:
        os.chdir(original_cwd)


@pytest.mark.integration
def test_should_raise_on_malformed_toml(tmp_path: os.PathLike) -> None:
    """Malformed TOML raises SystemExit with file path in message."""
    bad_config = tmp_path / "stoiquent.toml"  # type: ignore[operator]
    bad_config.write_text("invalid [[ toml syntax")
    with pytest.raises(SystemExit, match="Invalid TOML"):
        load_config(bad_config)  # type: ignore[arg-type]
