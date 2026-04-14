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


def test_should_parse_skills_section(tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("""\
[skills]
paths = ["/custom/skills"]
""")
    config = load_config(config_file)
    assert config.skills.paths == ["/custom/skills"]


def test_should_parse_sandbox_section(tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("""\
[sandbox]
backend = "none"
container_runtime = "podman"
tool_timeout = 60.0
""")
    config = load_config(config_file)
    assert config.sandbox.backend == "none"
    assert config.sandbox.container_runtime == "podman"
    assert config.sandbox.tool_timeout == 60.0


def test_should_parse_persistence_section(tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("""\
[persistence]
data_dir = "/custom/data"
""")
    config = load_config(config_file)
    assert config.persistence.data_dir == "/custom/data"


def test_should_parse_agent_section(tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("""\
[agent]
iteration_limit = 10
""")
    config = load_config(config_file)
    assert config.agent.iteration_limit == 10


def test_should_use_defaults_for_missing_sections(tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("[ui]\nmode = 'browser'\n")
    config = load_config(config_file)
    assert config.skills.paths == ["~/.agents/skills", "~/.stoiquent/skills"]
    assert config.sandbox.backend == "auto"
    assert config.persistence.data_dir == "~/.stoiquent"
    assert config.agent.iteration_limit == 25


def test_should_raise_system_exit_on_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.toml"
    with pytest.raises(SystemExit, match="Config file not found"):
        load_config(missing)


def test_should_raise_system_exit_on_permission_error(tmp_path: Path) -> None:
    config_file = tmp_path / "stoiquent.toml"
    config_file.write_text("[ui]\nmode = 'browser'\n")
    config_file.chmod(0o000)
    try:
        with pytest.raises(SystemExit, match="Cannot read"):
            load_config(config_file)
    finally:
        config_file.chmod(0o644)
