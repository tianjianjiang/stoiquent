"""Minimal NiceGUI app for Playwright MCP testing.

Uses FakeProvider so tests are deterministic without Ollama.
Start with: uv run python tests/e2e/serve_for_playwright.py
Then use Playwright MCP tools to interact at http://127.0.0.1:8080
"""

from __future__ import annotations

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.models import StreamChunk
from stoiquent.ui import layout
from tests.conftest import FakeProvider

provider = FakeProvider(
    chunks=[
        StreamChunk(content_delta="This is a test response from FakeProvider."),
        StreamChunk(finish_reason="stop"),
    ]
)
session = Session(provider=provider)


@ui.page("/")
async def page() -> None:
    await layout.render(session)


if __name__ == "__main__":
    ui.run(host="127.0.0.1", port=8080, reload=False, title="Stoiquent (Test)")
