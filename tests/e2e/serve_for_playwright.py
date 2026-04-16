"""Minimal NiceGUI app for Playwright MCP testing.

Uses FakeProvider so tests are deterministic without Ollama.
Start with: uv run python tests/e2e/serve_for_playwright.py
Then use Playwright MCP tools to interact at http://127.0.0.1:8080
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.models import Message, StreamChunk
from stoiquent.ui import layout


@dataclass
class _FakeProvider:
    """Inline provider for standalone script (avoids tests.conftest import).

    Keep in sync with tests.conftest.FakeProvider.
    """

    chunks: list[StreamChunk] = field(default_factory=list)

    async def stream(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self.chunks:
            yield chunk


def _make_session() -> Session:
    """Fresh session per page request to avoid state leaking between runs."""
    return Session(
        provider=_FakeProvider(
            chunks=[
                StreamChunk(content_delta="This is a test response from FakeProvider."),
                StreamChunk(finish_reason="stop"),
            ]
        )
    )


@ui.page("/")
async def page() -> None:
    await layout.render(_make_session())


if __name__ == "__main__":
    ui.run(host="127.0.0.1", port=8080, reload=False, title="Stoiquent (Test)")
