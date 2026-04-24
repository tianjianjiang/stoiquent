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
    from stoiquent.skills.controller import SkillController
    from stoiquent.skills.mcp_bridge import MCPBridge


@dataclass
class Session:
    provider: LLMProvider
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[Message] = field(default_factory=list)
    catalog: SkillCatalog | None = None
    controller: SkillController | None = None
    sandbox: SandboxBackend | None = None
    sandbox_policy: SandboxPolicy | None = None
    mcp_bridge: MCPBridge | None = None
    iteration_limit: int = 25
    tool_timeout: float = 300.0
    project_id: str | None = None
    project_instructions: str = ""
    # Warnings accumulated during startup hooks before any page is
    # rendered — ``ui.notify`` has no client context yet, so the UI
    # layer must drain these via :meth:`consume_startup_warnings` on
    # the first page mount.
    startup_warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.iteration_limit <= 0:
            raise ValueError(f"iteration_limit must be positive, got {self.iteration_limit}")
        if self.tool_timeout <= 0:
            raise ValueError(f"tool_timeout must be positive, got {self.tool_timeout}")

    def consume_startup_warnings(self) -> list[str]:
        """Return and clear queued startup warnings.

        Safe on the single-threaded NiceGUI event loop: the returned
        snapshot is stable while the in-place clear runs before any
        concurrent appender. Subsequent calls return ``[]`` until new
        warnings are queued, so multiple page renders don't replay the
        same notification.
        """
        warnings = list(self.startup_warnings)
        self.startup_warnings.clear()
        return warnings
