from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class StreamChunk(BaseModel):
    content_delta: str = ""
    reasoning_delta: str = ""
    tool_calls_delta: list[dict[str, Any]] | None = None
    finish_reason: str | None = None


class ProviderConfig(BaseModel):
    type: str = "openai"
    base_url: str
    model: str
    api_key: str = ""
    max_tokens: int = 8192
    supports_reasoning: bool = False
    native_tools: bool = True


class UIConfig(BaseModel):
    mode: Literal["native", "browser"] = "native"
    host: str = "127.0.0.1"
    port: int = 8080


class AppConfig(BaseModel):
    ui: UIConfig = Field(default_factory=UIConfig)
    default_provider: str = "local-qwen"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
