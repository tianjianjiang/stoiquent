from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    model_config = ConfigDict(extra="forbid")
    type: Literal["openai"] = "openai"
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: str = ""
    max_tokens: int = Field(default=8192, gt=0)
    supports_reasoning: bool = False
    native_tools: bool = True


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["native", "browser"] = "native"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(
        default_factory=lambda: ["~/.agents/skills", "~/.stoiquent/skills"]
    )


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = "auto"
    container_runtime: str = "auto"
    tool_timeout: float = Field(default=300.0, gt=0)


class PersistenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: str = "~/.stoiquent"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iteration_limit: int = Field(default=25, gt=0)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ui: UIConfig = Field(default_factory=UIConfig)
    default_provider: str = "local-qwen"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)

    @model_validator(mode="after")
    def _check_default_provider(self) -> Self:
        if self.providers and self.default_provider not in self.providers:
            raise ValueError(
                f"default_provider '{self.default_provider}' not in providers: "
                f"{list(self.providers)}"
            )
        return self
