from __future__ import annotations

import os
from pathlib import Path

from stoiquent.config import load_config


class TestLoadConfig:
    def test_missing_config_returns_defaults(self, tmp_path: Path) -> None:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = load_config()
            assert config.ui.mode == "native"
            assert config.default_provider == "local-qwen"
            assert config.providers == {}
        finally:
            os.chdir(original_cwd)

    def test_load_from_explicit_path(self, tmp_config_file: Path) -> None:
        config = load_config(tmp_config_file)
        assert config.ui.mode == "browser"
        assert config.default_provider == "test-provider"
        assert "test-provider" in config.providers

    def test_provider_config_parsed(self, tmp_config_file: Path) -> None:
        config = load_config(tmp_config_file)
        prov = config.providers["test-provider"]
        assert prov.base_url == "http://localhost:11434/v1"
        assert prov.model == "test-model"
        assert prov.supports_reasoning is True
        assert prov.native_tools is False

    def test_env_var_interpolation(
        self, tmp_config_file: Path, monkeypatch: object
    ) -> None:
        import pytest

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("TEST_API_KEY", "secret-key-123")
        try:
            config = load_config(tmp_config_file)
            assert config.providers["test-provider"].api_key == "secret-key-123"
        finally:
            monkeypatch.undo()

    def test_missing_env_var_becomes_empty(self, tmp_config_file: Path) -> None:
        os.environ.pop("TEST_API_KEY", None)
        config = load_config(tmp_config_file)
        assert config.providers["test-provider"].api_key == ""

    def test_load_from_project_root(self) -> None:
        config = load_config()
        assert config.default_provider == "local-qwen"
        assert "local-qwen" in config.providers
        assert config.providers["local-qwen"].model == "qwen3:32b"
