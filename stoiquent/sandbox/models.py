from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BindMount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    read_only: bool = True


class SandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_seconds: float = Field(default=120.0, gt=0)
    memory_mb: int = Field(default=512, gt=0)
    disk_mb: int = Field(default=100, gt=0)
    max_pids: int = Field(default=64, gt=0)
    network: Literal["none", "host"] = "none"
    bind_mounts: list[BindMount] = Field(default_factory=list)


class SandboxResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    wall_time_seconds: float = Field(default=0.0, ge=0)
