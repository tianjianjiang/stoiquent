from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import Message, ProviderConfig


def _make_provider(**overrides: object) -> OpenAICompatProvider:
    defaults: dict = {"base_url": "http://localhost:11434/v1", "model": "test"}
    defaults.update(overrides)
    return OpenAICompatProvider(ProviderConfig(**defaults))


async def _async_lines(*lines: str):
    for line in lines:
        yield line


def _mock_stream_context(mock_stream: MagicMock, *sse_lines: str) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _async_lines(*sse_lines)
    mock_stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)


@pytest.mark.asyncio
async def test_should_include_auth_header_when_api_key_set() -> None:
    provider = _make_provider(api_key="test-key-123")
    messages = [Message(role="user", content="hi")]

    with patch.object(provider._client, "stream") as mock_stream:
        _mock_stream_context(mock_stream, "data: [DONE]")
        async for _ in provider.stream(messages):
            pass
        assert mock_stream.call_args[1]["headers"]["Authorization"] == "Bearer test-key-123"

    await provider.close()


@pytest.mark.asyncio
async def test_should_omit_auth_header_when_api_key_empty() -> None:
    provider = _make_provider(api_key="")
    messages = [Message(role="user", content="hi")]

    with patch.object(provider._client, "stream") as mock_stream:
        _mock_stream_context(mock_stream, "data: [DONE]")
        async for _ in provider.stream(messages):
            pass
        assert "Authorization" not in mock_stream.call_args[1]["headers"]

    await provider.close()


@pytest.mark.asyncio
async def test_should_include_tools_when_native_tools_enabled() -> None:
    provider = _make_provider(native_tools=True)
    messages = [Message(role="user", content="hi")]
    tools = [{"type": "function", "function": {"name": "test"}}]

    with patch.object(provider._client, "stream") as mock_stream:
        _mock_stream_context(mock_stream, "data: [DONE]")
        async for _ in provider.stream(messages, tools=tools):
            pass
        assert "tools" in mock_stream.call_args[1]["json"]

    await provider.close()


@pytest.mark.asyncio
async def test_should_omit_tools_when_native_tools_disabled() -> None:
    provider = _make_provider(native_tools=False)
    messages = [Message(role="user", content="hi")]
    tools = [{"type": "function", "function": {"name": "test"}}]

    with patch.object(provider._client, "stream") as mock_stream:
        _mock_stream_context(mock_stream, "data: [DONE]")
        async for _ in provider.stream(messages, tools=tools):
            pass
        assert "tools" not in mock_stream.call_args[1]["json"]

    await provider.close()


@pytest.mark.asyncio
async def test_should_raise_timeout_error_on_timeout() -> None:
    provider = _make_provider()
    messages = [Message(role="user", content="hi")]

    with patch.object(provider._client, "stream") as mock_stream:
        mock_stream.side_effect = httpx.ReadTimeout("read timed out")
        with pytest.raises(TimeoutError, match="timed out"):
            async for _ in provider.stream(messages):
                pass

    await provider.close()


@pytest.mark.asyncio
async def test_should_raise_runtime_error_on_non_404_http_error() -> None:
    provider = _make_provider()
    messages = [Message(role="user", content="hi")]

    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch.object(provider._client, "stream") as mock_stream:
        mock_stream.side_effect = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=mock_response
        )
        with pytest.raises(RuntimeError, match="HTTP 500"):
            async for _ in provider.stream(messages):
                pass

    await provider.close()
