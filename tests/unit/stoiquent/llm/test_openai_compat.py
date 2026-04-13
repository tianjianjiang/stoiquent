from __future__ import annotations

import json

from stoiquent.llm.openai_compat import _parse_sse_line, _serialize_message
from stoiquent.models import Message, ToolCall


def test_should_parse_valid_content_chunk() -> None:
    data = {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]}
    line = f"data: {json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=False)
    assert chunk is not None
    assert chunk.content_delta == "hello"
    assert chunk.reasoning_delta == ""


def test_should_parse_done_signal() -> None:
    chunk = _parse_sse_line("data: [DONE]", supports_reasoning=False)
    assert chunk is not None
    assert chunk.finish_reason == "stop"


def test_should_skip_non_data_lines() -> None:
    assert _parse_sse_line("", supports_reasoning=False) is None
    assert _parse_sse_line(": comment", supports_reasoning=False) is None
    assert _parse_sse_line("event: ping", supports_reasoning=False) is None


def test_should_skip_malformed_json() -> None:
    chunk = _parse_sse_line("data: {invalid", supports_reasoning=False)
    assert chunk is None


def test_should_skip_empty_choices() -> None:
    chunk = _parse_sse_line('data: {"choices": []}', supports_reasoning=False)
    assert chunk is None


def test_should_extract_api_native_reasoning() -> None:
    data = {
        "choices": [
            {
                "delta": {"content": "answer", "reasoning_content": "thinking..."},
                "finish_reason": None,
            }
        ]
    }
    line = f"data: {json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=True)
    assert chunk is not None
    assert chunk.content_delta == "answer"
    assert chunk.reasoning_delta == "thinking..."


def test_should_handle_null_reasoning_content() -> None:
    data = {
        "choices": [
            {
                "delta": {"content": "answer", "reasoning_content": None},
                "finish_reason": None,
            }
        ]
    }
    line = f"data: {json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=True)
    assert chunk is not None
    assert chunk.reasoning_delta == ""


def test_should_not_extract_think_tags_in_sse(
) -> None:
    """Think tag extraction now happens in loop.py, not per-chunk."""
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
    assert chunk.content_delta == "<think>reasoning</think>answer"
    assert chunk.reasoning_delta == ""


def test_should_propagate_finish_reason() -> None:
    data = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    line = f"data: {json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=False)
    assert chunk is not None
    assert chunk.finish_reason == "stop"


def test_should_pass_tool_calls_delta() -> None:
    tool_delta = [{"index": 0, "function": {"name": "test", "arguments": '{"a":'}}]
    data = {"choices": [{"delta": {"tool_calls": tool_delta}, "finish_reason": None}]}
    line = f"data: {json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=False)
    assert chunk is not None
    assert chunk.tool_calls_delta == tool_delta


def test_should_parse_data_without_space_after_colon() -> None:
    data = {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
    line = f"data:{json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=False)
    assert chunk is not None
    assert chunk.content_delta == "hi"


def test_should_handle_null_content_delta() -> None:
    data = {"choices": [{"delta": {"content": None}, "finish_reason": None}]}
    line = f"data: {json.dumps(data)}"
    chunk = _parse_sse_line(line, supports_reasoning=False)
    assert chunk is not None
    assert chunk.content_delta == ""


def test_should_serialize_user_message() -> None:
    msg = Message(role="user", content="hello")
    result = _serialize_message(msg)
    assert result == {"role": "user", "content": "hello"}


def test_should_serialize_assistant_with_tool_calls() -> None:
    tc = ToolCall(id="call_1", name="read", arguments={"path": "/tmp"})
    msg = Message(role="assistant", content=None, tool_calls=[tc])
    result = _serialize_message(msg)
    assert result["role"] == "assistant"
    assert result["content"] is None
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["id"] == "call_1"


def test_should_serialize_tool_result() -> None:
    msg = Message(role="tool", content="file contents", tool_call_id="call_1")
    result = _serialize_message(msg)
    assert result == {
        "role": "tool",
        "content": "file contents",
        "tool_call_id": "call_1",
    }


def test_should_serialize_system_message() -> None:
    msg = Message(role="system", content="You are helpful.")
    result = _serialize_message(msg)
    assert result == {"role": "system", "content": "You are helpful."}
