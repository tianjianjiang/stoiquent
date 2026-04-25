from __future__ import annotations

import functools
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeAlias

from nicegui import page as _nicegui_page

from stoiquent.models import (
    AppConfig,
    Message,
    PersistenceConfig,
    ProviderConfig,
    StreamChunk,
)
from stoiquent.persistence import ConversationStore
from stoiquent.projects import ProjectStore
from stoiquent.skills.models import Skill, SkillMeta

pytest_plugins = ["nicegui.testing.plugin"]


# Bump @ui.page's `response_timeout` default from 3s to 15s for the test
# suite. CI runners are slower than dev machines; under coverage
# instrumentation the page-build coroutine can miss the 3s window, which
# causes nicegui to call `client.delete()` and the next `User.open()` to
# raise `KeyError(client_id)` deep inside `Client.instances[client_id]`.
# The 21 KeyError failures we saw on PR #33 in run 24886651427 all match
# this pattern. Increasing the default makes the suite tolerant of CI
# scheduling jitter; tests that pass an explicit `response_timeout=` to
# `@ui.page()` continue to honour their own value.
_orig_page_init = _nicegui_page.page.__init__


@functools.wraps(_orig_page_init)
def _page_init_with_ci_safe_timeout(
    self: Any, path: str, *args: Any, response_timeout: float = 15.0, **kwargs: Any
) -> None:
    _orig_page_init(self, path, *args, response_timeout=response_timeout, **kwargs)


_nicegui_page.page.__init__ = _page_init_with_ci_safe_timeout

Turn: TypeAlias = list[StreamChunk]
"""Chunks yielded within a single ``FakeToolCallingProvider.stream`` call."""


@dataclass
class FakeProvider:
    """Deterministic LLM provider for testing. Not a mock -- a real implementation
    of the LLMProvider protocol that yields pre-configured chunks."""

    chunks: list[StreamChunk] = field(default_factory=list)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self.chunks:
            yield chunk


@dataclass
class FakeToolCallingProvider:
    """Scripted multi-turn LLM provider for agent-loop tests.

    ``scripts[i]`` is the chunk sequence yielded on the i-th call to
    ``stream`` — mirroring how ``run_agent_loop`` re-invokes the provider
    each iteration with freshly built messages. Raises ``IndexError`` when
    the loop asks for more turns than scripted, so under-specification
    surfaces as a loud test failure instead of a silent no-op turn.

    Each call records the ``messages`` / ``tools`` arguments into
    ``calls``, so tests can assert that ``build_messages`` is feeding the
    loop the shape they expect (e.g. a ``role=tool`` entry on turn 2).

    Because ``stream`` is an async generator, the guard's ``IndexError``
    surfaces on the first ``__anext__`` of the returned iterator — i.e.
    inside the agent loop's ``async for``, not at the ``stream(...)`` call
    site.
    """

    scripts: list[Turn] = field(default_factory=list)
    call_count: int = field(init=False, default=0)
    calls: list[dict[str, Any]] = field(init=False, default_factory=list)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        if self.call_count >= len(self.scripts):
            last_role = messages[-1].role if messages else None
            raise IndexError(
                f"FakeToolCallingProvider: turn {self.call_count} requested, "
                f"only {len(self.scripts)} scripted "
                f"(messages={len(messages)}, last_role={last_role!r})"
            )
        self.calls.append({"messages": list(messages), "tools": tools})
        turn = self.scripts[self.call_count]
        self.call_count += 1
        for chunk in turn:
            yield chunk


def tool_call_script(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    final_reply: str,
    call_id: str = "call_1",
    preface: str = "",
) -> list[Turn]:
    """Two-turn script for a tool-call round trip.

    Turn 1 emits the tool call (with optional ``preface`` text streamed
    alongside, mirroring real providers that narrate before calling).
    Turn 2 emits ``final_reply`` after the loop injects the tool result.
    """
    turn1: Turn = []
    if preface:
        turn1.append(StreamChunk(content_delta=preface))
    turn1.append(
        StreamChunk(
            tool_calls_delta=[
                {
                    "index": 0,
                    "id": call_id,
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments),
                    },
                }
            ],
            finish_reason="tool_calls",
        )
    )
    return [
        turn1,
        [
            StreamChunk(content_delta=final_reply),
            StreamChunk(finish_reason="stop"),
        ],
    ]


async def async_noop(_chunk: StreamChunk) -> None:
    """No-op ``on_chunk`` callback for tests that ignore stream events."""
    return None


def make_store(tmp_path: Path) -> ConversationStore:
    """Create a ConversationStore backed by a temporary directory."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    store.ensure_dirs()
    return store


def make_project_store(tmp_path: Path) -> ProjectStore:
    """Create a ProjectStore backed by a temporary directory."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ProjectStore(config)
    store.ensure_dirs()
    return store


def two_provider_config(
    default: str = "local-qwen", second: str = "other"
) -> AppConfig:
    """Create an AppConfig with two providers for testing."""
    return AppConfig(
        default_provider=default,
        providers={
            "local-qwen": ProviderConfig(
                base_url="http://localhost:11434/v1", model="qwen3:32b"
            ),
            second: ProviderConfig(
                base_url="http://localhost:11434/v1", model="other-model"
            ),
        },
    )


def make_skill(name: str, description: str, active: bool = False) -> Skill:
    """Create a Skill instance for testing."""
    return Skill(
        meta=SkillMeta(name=name, description=description),
        path=Path("/fake"),
        instructions="",
        active=active,
        source="config",
    )
