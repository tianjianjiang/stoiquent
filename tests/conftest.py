from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from stoiquent.models import Message, PersistenceConfig, StreamChunk
from stoiquent.persistence import ConversationStore
from stoiquent.skills.models import Skill, SkillMeta

pytest_plugins = ["nicegui.testing.plugin"]


@dataclass
class FakeProvider:
    """Deterministic LLM provider for testing. Not a mock -- a real implementation
    of the LLMProvider protocol that yields pre-configured chunks."""

    chunks: list[StreamChunk] = field(default_factory=list)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self.chunks:
            yield chunk


def make_store(tmp_path: Path) -> ConversationStore:
    """Create a ConversationStore backed by a temporary directory."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    store.ensure_dirs()
    return store


def make_skill(name: str, description: str, active: bool = False) -> Skill:
    """Create a Skill instance for testing."""
    return Skill(
        meta=SkillMeta(name=name, description=description),
        path=Path("/fake"),
        instructions="",
        active=active,
        source="config",
    )
