from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.models import Message, ProviderConfig


@pytest.fixture
def sample_provider_config() -> ProviderConfig:
    return ProviderConfig(
        base_url="http://localhost:11434/v1",
        model="qwen3:32b",
        supports_reasoning=True,
    )


@pytest.fixture
def sample_messages() -> list[Message]:
    return [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there!"),
        Message(role="user", content="How are you?"),
    ]


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
