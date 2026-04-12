from __future__ import annotations

import os
from pathlib import Path

import pytest

from stoiquent.config import load_config


@pytest.fixture
def tmp_config_file(tmp_path: Path) -> Path:
    config = tmp_path / "stoiquent.toml"
    config.write_text("""\
[ui]
mode = "browser"

[llm]
default = "test-provider"

[llm.providers.test-provider]
type = "openai"
base_url = "http://localhost:11434/v1"
model = "test-model"
api_key = "${TEST_API_KEY}"
supports_reasoning = true
native_tools = false
""")
    return config


def test_should_return_defaults_when_config_missing(tmp_path: Path) -> None:
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        config = load_config()
        assert config.ui.mode == "native"
        assert config.default_provider == "local-qwen"
        assert config.providers == {}
    finally:
        os.chdir(original_cwd)


def test_should_load_from_explicit_path(tmp_config_file: Path) -> None:
    config = load_config(tmp_config_file)
    assert config.ui.mode == "browser"
    assert config.default_provider == "test-provider"
    assert "test-provider" in config.providers


def test_should_parse_provider_config(tmp_config_file: Path) -> None:
    config = load_config(tmp_config_file)
    prov = config.providers["test-provider"]
    assert prov.base_url == "http://localhost:11434/v1"
    assert prov.model == "test-model"
    assert prov.supports_reasoning is True
    assert prov.native_tools is False


def test_should_interpolate_env_vars(
    tmp_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "secret-key-123")
    config = load_config(tmp_config_file)
    assert config.providers["test-provider"].api_key == "secret-key-123"


def test_should_use_empty_string_for_missing_env_var(
    tmp_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    config = load_config(tmp_config_file)
    assert config.providers["test-provider"].api_key == ""
