from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from stoiquent.models import Message, ProviderConfig, StreamChunk

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        headers: dict[str, str] = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        payload: dict = {
            "model": self.config.model,
            "messages": [_serialize_message(m) for m in messages],
            "stream": True,
            "max_tokens": self.config.max_tokens,
        }
        if tools and self.config.native_tools:
            payload["tools"] = tools

        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    chunk = _parse_sse_line(line, self.config.supports_reasoning)
                    if chunk is not None:
                        yield chunk
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot connect to LLM at {self.config.base_url}. "
                "Ensure Ollama is running (ollama serve)."
            ) from None
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"LLM request timed out: {e}. The model may be loading."
            ) from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 404:
                raise RuntimeError(
                    f"Model '{self.config.model}' not found. "
                    f"Run: ollama pull {self.config.model}"
                ) from None
            raise RuntimeError(
                f"LLM returned HTTP {status}. Check provider configuration."
            ) from e

    async def close(self) -> None:
        await self._client.aclose()


def _serialize_message(msg: Message) -> dict:
    result: dict = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        result["tool_call_id"] = msg.tool_call_id
    return result


def _parse_sse_line(line: str, supports_reasoning: bool) -> StreamChunk | None:
    if not line.startswith("data: "):
        return None
    data = line[6:].strip()
    if data == "[DONE]":
        return StreamChunk(finish_reason="stop")

    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Skipping malformed SSE data: %s", data[:200])
        return None

    choices = obj.get("choices", [])
    if not choices:
        return None

    delta = choices[0].get("delta", {})
    finish_reason = choices[0].get("finish_reason")

    content_delta = delta.get("content", "")
    reasoning_delta = ""

    if supports_reasoning and "reasoning_content" in delta:
        reasoning_delta = delta["reasoning_content"] or ""

    tool_calls_delta = delta.get("tool_calls")

    return StreamChunk(
        content_delta=content_delta,
        reasoning_delta=reasoning_delta,
        tool_calls_delta=tool_calls_delta,
        finish_reason=finish_reason,
    )
