from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from stoiquent.models import Message

if TYPE_CHECKING:
    from stoiquent.llm.provider import LLMProvider
    from stoiquent.sandbox.base import SandboxBackend
    from stoiquent.sandbox.models import SandboxPolicy
    from stoiquent.skills.catalog import SkillCatalog
    from stoiquent.skills.mcp_bridge import MCPBridge


@dataclass
class Session:
    provider: LLMProvider
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[Message] = field(default_factory=list)
    catalog: SkillCatalog | None = None
    sandbox: SandboxBackend | None = None
    sandbox_policy: SandboxPolicy | None = None
    mcp_bridge: MCPBridge | None = None
    iteration_limit: int = 25
    tool_timeout: float = 300.0

    def __post_init__(self) -> None:
        if self.iteration_limit <= 0:
            raise ValueError(f"iteration_limit must be positive, got {self.iteration_limit}")
        if self.tool_timeout <= 0:
            raise ValueError(f"tool_timeout must be positive, got {self.tool_timeout}")
