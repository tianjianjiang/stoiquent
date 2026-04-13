from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillToolDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class MCPServerDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class MCPAppDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str = Field(min_length=1)
    permissions: list[str] = Field(default_factory=list)
    csp: list[str] = Field(default_factory=list)


class SkillMeta(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    tools: list[SkillToolDef] = Field(default_factory=list)
    mcp_servers: list[MCPServerDef] = Field(default_factory=list)
    mcp_app: MCPAppDef | None = None


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: SkillMeta
    path: Path
    instructions: str = ""
    active: bool = False
    source: Literal["user", "project", "config"] = "user"
