from __future__ import annotations

import pytest
from pydantic import ValidationError

from stoiquent.models import (
    AgentConfig,
    AppConfig,
    Message,
    PersistenceConfig,
    ProviderConfig,
    SandboxConfig,
    SkillsConfig,
    StreamChunk,
    ToolCall,
)


def test_should_accept_valid_roles() -> None:
    for role in ("system", "user", "assistant", "tool"):
        msg = Message(role=role, content="test")
        assert msg.role == role


def test_should_reject_invalid_role() -> None:
    with pytest.raises(ValidationError):
        Message(role="invalid", content="test")


def test_should_allow_none_content() -> None:
    msg = Message(role="assistant", content=None)
    assert msg.content is None


def test_should_default_content_to_none() -> None:
    msg = Message(role="user")
    assert msg.content is None


def test_should_store_reasoning_on_assistant() -> None:
    msg = Message(role="assistant", content="answer", reasoning="thinking...")
    assert msg.reasoning == "thinking..."


def test_should_store_tool_calls_on_assistant() -> None:
    tc = ToolCall(id="call_1", name="test", arguments={"a": 1})
    msg = Message(role="assistant", tool_calls=[tc])
    assert len(msg.tool_calls) == 1


def test_should_store_tool_call_id_on_tool_message() -> None:
    msg = Message(role="tool", content="result", tool_call_id="call_1")
    assert msg.tool_call_id == "call_1"


def test_should_create_valid_tool_call() -> None:
    tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/x"})
    assert tc.id == "call_1"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "/tmp/x"}


def test_should_reject_empty_tool_call_id() -> None:
    with pytest.raises(ValidationError):
        ToolCall(id="", name="test")


def test_should_reject_empty_tool_call_name() -> None:
    with pytest.raises(ValidationError):
        ToolCall(id="call_1", name="")


def test_should_default_tool_call_arguments_to_empty_dict() -> None:
    tc = ToolCall(id="call_1", name="test")
    assert tc.arguments == {}


def test_should_keep_tool_call_arguments_independent() -> None:
    tc1 = ToolCall(id="1", name="a")
    tc2 = ToolCall(id="2", name="b")
    tc1.arguments["key"] = "value"
    assert "key" not in tc2.arguments


def test_should_create_stream_chunk_with_defaults() -> None:
    chunk = StreamChunk()
    assert chunk.content_delta == ""
    assert chunk.reasoning_delta == ""
    assert chunk.tool_calls_delta is None
    assert chunk.finish_reason is None


def test_should_create_stream_chunk_with_content() -> None:
    chunk = StreamChunk(content_delta="hello", reasoning_delta="thinking")
    assert chunk.content_delta == "hello"
    assert chunk.reasoning_delta == "thinking"


def test_should_reject_provider_config_without_required_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig()  # type: ignore[call-arg]


def test_should_create_provider_config_with_defaults() -> None:
    pc = ProviderConfig(base_url="http://localhost:11434/v1", model="qwen3:32b")
    assert pc.type == "openai"
    assert pc.api_key == ""
    assert pc.max_tokens == 8192
    assert pc.supports_reasoning is False
    assert pc.native_tools is True


def test_should_reject_provider_config_with_zero_max_tokens() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(base_url="http://localhost:11434/v1", model="test", max_tokens=0)


def test_should_create_app_config_with_defaults() -> None:
    config = AppConfig()
    assert config.ui.mode == "native"
    assert config.default_provider == "local-qwen"
    assert config.providers == {}


def test_should_reject_app_config_with_invalid_default_provider() -> None:
    with pytest.raises(ValidationError):
        AppConfig(
            default_provider="nonexistent",
            providers={"real": ProviderConfig(base_url="http://x", model="m")},
        )


def test_should_accept_app_config_with_empty_providers() -> None:
    config = AppConfig(default_provider="anything", providers={})
    assert config.default_provider == "anything"


def test_should_create_skills_config_with_defaults() -> None:
    config = SkillsConfig()
    assert config.paths == ["~/.agents/skills", "~/.stoiquent/skills"]


def test_should_create_skills_config_with_custom_paths() -> None:
    config = SkillsConfig(paths=["/custom/skills"])
    assert config.paths == ["/custom/skills"]


def test_skills_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SkillsConfig(unknown="field")


def test_should_create_sandbox_config_with_defaults() -> None:
    config = SandboxConfig()
    assert config.backend == "auto"
    assert config.container_runtime == "auto"
    assert config.tool_timeout == 300.0


def test_sandbox_config_rejects_zero_timeout() -> None:
    with pytest.raises(ValidationError, match="tool_timeout"):
        SandboxConfig(tool_timeout=0)


def test_sandbox_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SandboxConfig(unknown="field")


def test_should_create_persistence_config_with_defaults() -> None:
    config = PersistenceConfig()
    assert config.data_dir == "~/.stoiquent"


def test_persistence_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        PersistenceConfig(unknown="field")


def test_should_create_agent_config_with_defaults() -> None:
    config = AgentConfig()
    assert config.iteration_limit == 25


def test_agent_config_rejects_zero_iteration_limit() -> None:
    with pytest.raises(ValidationError, match="iteration_limit"):
        AgentConfig(iteration_limit=0)


def test_agent_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AgentConfig(unknown="field")


def test_app_config_includes_new_sections_with_defaults() -> None:
    config = AppConfig()
    assert isinstance(config.skills, SkillsConfig)
    assert isinstance(config.sandbox, SandboxConfig)
    assert isinstance(config.persistence, PersistenceConfig)
    assert isinstance(config.agent, AgentConfig)
