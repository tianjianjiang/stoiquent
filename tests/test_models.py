from __future__ import annotations

import pytest
from pydantic import ValidationError

from stoiquent.models import (
    AppConfig,
    Message,
    ProviderConfig,
    StreamChunk,
    ToolCall,
)


class TestMessage:
    def test_valid_roles(self) -> None:
        for role in ("system", "user", "assistant", "tool"):
            msg = Message(role=role, content="test")
            assert msg.role == role

    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Message(role="invalid", content="test")

    def test_content_can_be_none(self) -> None:
        msg = Message(role="assistant", content=None)
        assert msg.content is None

    def test_content_defaults_to_none(self) -> None:
        msg = Message(role="user")
        assert msg.content is None

    def test_reasoning_optional(self) -> None:
        msg = Message(role="assistant", content="answer", reasoning="thinking...")
        assert msg.reasoning == "thinking..."

    def test_tool_calls_optional(self) -> None:
        tc = ToolCall(id="call_1", name="test", arguments={"a": 1})
        msg = Message(role="assistant", tool_calls=[tc])
        assert len(msg.tool_calls) == 1

    def test_tool_call_id_optional(self) -> None:
        msg = Message(role="tool", content="result", tool_call_id="call_1")
        assert msg.tool_call_id == "call_1"


class TestToolCall:
    def test_valid_tool_call(self) -> None:
        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/x"})
        assert tc.id == "call_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/x"}

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolCall(id="", name="test")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolCall(id="call_1", name="")

    def test_arguments_defaults_to_empty_dict(self) -> None:
        tc = ToolCall(id="call_1", name="test")
        assert tc.arguments == {}

    def test_arguments_are_independent(self) -> None:
        tc1 = ToolCall(id="1", name="a")
        tc2 = ToolCall(id="2", name="b")
        tc1.arguments["key"] = "value"
        assert "key" not in tc2.arguments


class TestStreamChunk:
    def test_defaults(self) -> None:
        chunk = StreamChunk()
        assert chunk.content_delta == ""
        assert chunk.reasoning_delta == ""
        assert chunk.tool_calls_delta is None
        assert chunk.finish_reason is None

    def test_with_content(self) -> None:
        chunk = StreamChunk(content_delta="hello", reasoning_delta="thinking")
        assert chunk.content_delta == "hello"
        assert chunk.reasoning_delta == "thinking"


class TestProviderConfig:
    def test_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            ProviderConfig()  # type: ignore[call-arg]

    def test_minimal_config(self) -> None:
        pc = ProviderConfig(base_url="http://localhost:11434/v1", model="qwen3:32b")
        assert pc.type == "openai"
        assert pc.api_key == ""
        assert pc.max_tokens == 8192
        assert pc.supports_reasoning is False
        assert pc.native_tools is True

    def test_full_config(self, sample_provider_config: ProviderConfig) -> None:
        assert sample_provider_config.supports_reasoning is True


class TestAppConfig:
    def test_defaults(self) -> None:
        config = AppConfig()
        assert config.ui.mode == "native"
        assert config.default_provider == "local-qwen"
        assert config.providers == {}
