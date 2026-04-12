from __future__ import annotations

import json

from stoiquent.llm.openai_compat import _parse_sse_line, _serialize_message
from stoiquent.models import Message, ToolCall


class TestParseSSELine:
    def test_valid_content_chunk(self) -> None:
        data = {
            "choices": [{"delta": {"content": "hello"}, "finish_reason": None}]
        }
        line = f"data: {json.dumps(data)}"
        chunk = _parse_sse_line(line, supports_reasoning=False)
        assert chunk is not None
        assert chunk.content_delta == "hello"
        assert chunk.reasoning_delta == ""

    def test_done_signal(self) -> None:
        chunk = _parse_sse_line("data: [DONE]", supports_reasoning=False)
        assert chunk is not None
        assert chunk.finish_reason == "stop"

    def test_non_data_line_returns_none(self) -> None:
        assert _parse_sse_line("", supports_reasoning=False) is None
        assert _parse_sse_line(": comment", supports_reasoning=False) is None
        assert _parse_sse_line("event: ping", supports_reasoning=False) is None

    def test_malformed_json_returns_none(self) -> None:
        chunk = _parse_sse_line("data: {invalid", supports_reasoning=False)
        assert chunk is None

    def test_empty_choices_returns_none(self) -> None:
        chunk = _parse_sse_line('data: {"choices": []}', supports_reasoning=False)
        assert chunk is None

    def test_reasoning_content_api_native(self) -> None:
        data = {
            "choices": [
                {
                    "delta": {
                        "content": "answer",
                        "reasoning_content": "thinking...",
                    },
                    "finish_reason": None,
                }
            ]
        }
        line = f"data: {json.dumps(data)}"
        chunk = _parse_sse_line(line, supports_reasoning=True)
        assert chunk is not None
        assert chunk.content_delta == "answer"
        assert chunk.reasoning_delta == "thinking..."

    def test_think_tag_extraction(self) -> None:
        data = {
            "choices": [
                {
                    "delta": {"content": "<think>reasoning</think>answer"},
                    "finish_reason": None,
                }
            ]
        }
        line = f"data: {json.dumps(data)}"
        chunk = _parse_sse_line(line, supports_reasoning=False)
        assert chunk is not None
        assert chunk.content_delta == "answer"
        assert chunk.reasoning_delta == "reasoning"

    def test_finish_reason_propagated(self) -> None:
        data = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        line = f"data: {json.dumps(data)}"
        chunk = _parse_sse_line(line, supports_reasoning=False)
        assert chunk is not None
        assert chunk.finish_reason == "stop"

    def test_tool_calls_delta(self) -> None:
        tool_delta = [{"index": 0, "function": {"name": "test", "arguments": '{"a":'}}]
        data = {
            "choices": [
                {"delta": {"tool_calls": tool_delta}, "finish_reason": None}
            ]
        }
        line = f"data: {json.dumps(data)}"
        chunk = _parse_sse_line(line, supports_reasoning=False)
        assert chunk is not None
        assert chunk.tool_calls_delta == tool_delta


class TestSerializeMessage:
    def test_user_message(self) -> None:
        msg = Message(role="user", content="hello")
        result = _serialize_message(msg)
        assert result == {"role": "user", "content": "hello"}

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="call_1", name="read", arguments={"path": "/tmp"})
        msg = Message(role="assistant", content=None, tool_calls=[tc])
        result = _serialize_message(msg)
        assert result["role"] == "assistant"
        assert "content" not in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["type"] == "function"
        assert result["tool_calls"][0]["function"]["name"] == "read"

    def test_tool_result_message(self) -> None:
        msg = Message(role="tool", content="file contents", tool_call_id="call_1")
        result = _serialize_message(msg)
        assert result == {
            "role": "tool",
            "content": "file contents",
            "tool_call_id": "call_1",
        }

    def test_system_message(self) -> None:
        msg = Message(role="system", content="You are helpful.")
        result = _serialize_message(msg)
        assert result == {"role": "system", "content": "You are helpful."}
