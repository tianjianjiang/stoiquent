"""End-to-end test: User → LLM (qwen3:0.6b) → tool call → Apple Containers → result → LLM answer.

This test proves the full stoiquent system works on macOS with a real local LLM
and real VM-level sandbox isolation via Apple Containers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import StreamChunk
from stoiquent.sandbox.apple import AppleContainersBackend
from stoiquent.sandbox.policy import default_policy
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.models import Skill, SkillMeta, SkillToolDef

from stoiquent.models import ProviderConfig
from tests.integration.conftest import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    skip_no_model,
    skip_no_ollama,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


def _apple_containers_available() -> bool:
    path = shutil.which("container") or "/opt/local/bin/container"
    if not os.path.isfile(path):
        return False
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


skip_no_apple = pytest.mark.skipif(
    not _apple_containers_available(),
    reason="Apple Containers not available (install: sudo port install container)",
)


def _make_e2e_session(provider: OpenAICompatProvider) -> Session:
    """Create a session with real LLM + real Apple Containers sandbox."""
    skill = Skill(
        meta=SkillMeta(
            name="hello-world",
            description="A simple greeting skill for testing",
            tools=[
                SkillToolDef(
                    name="greet",
                    description="Greet someone by name. Takes a JSON argument with a 'name' field.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "The name of the person to greet",
                            }
                        },
                        "required": ["name"],
                    },
                )
            ],
        ),
        path=FIXTURES / "hello-world",
        instructions="Use the greet tool when asked to greet someone.",
        active=True,
    )
    catalog = SkillCatalog({"hello-world": skill})

    # Use Apple Containers with python image (greet.py needs Python)
    container_path = shutil.which("container") or "/opt/local/bin/container"
    sandbox = AppleContainersBackend(container_path, image="python:3.12-slim")

    return Session(
        provider=provider,
        catalog=catalog,
        sandbox=sandbox,
        sandbox_policy=default_policy(),
        iteration_limit=5,
        tool_timeout=60.0,
    )


@skip_no_ollama
@skip_no_model
@skip_no_apple
@pytest.mark.asyncio
async def test_full_round_trip_with_apple_containers() -> None:
    """Full e2e: user -> qwen3:0.6b -> tool call -> Apple Containers VM -> result -> final answer."""
    config = ProviderConfig(
        base_url=f"{OLLAMA_BASE_URL}/v1",
        model=OLLAMA_MODEL,
        supports_reasoning=True,
        native_tools=True,
    )
    provider = OpenAICompatProvider(config)
    try:
        session = _make_e2e_session(provider)
        chunks: list[StreamChunk] = []

        async def on_chunk(chunk: StreamChunk) -> None:
            chunks.append(chunk)

        await run_agent_loop(
            session,
            "Use the greet tool to greet Alice. Do not write the greeting yourself, you must use the tool.",
            on_chunk,
        )

        # Should have: user, assistant (with tool_calls), tool (result), assistant (final)
        assert len(session.messages) >= 4, (
            f"Expected at least 4 messages, "
            f"got {len(session.messages)}: {[m.role for m in session.messages]}"
        )

        # Tool was executed in Apple Containers and returned result
        tool_msgs = [m for m in session.messages if m.role == "tool"]
        assert len(tool_msgs) >= 1, (
            f"Expected tool message, got roles: {[m.role for m in session.messages]}"
        )
        assert any("Hello, Alice!" in (m.content or "") for m in tool_msgs), (
            f"Tool output should contain 'Hello, Alice!', got: "
            f"{[m.content for m in tool_msgs]}"
        )

        # LLM made a tool call
        assistant_with_tools = [
            m for m in session.messages if m.role == "assistant" and m.tool_calls
        ]
        assert len(assistant_with_tools) >= 1
        assert any(tc.name == "greet" for tc in assistant_with_tools[0].tool_calls)

        # Final answer from LLM
        assert session.messages[-1].role == "assistant"
        assert session.messages[-1].content is not None
    finally:
        await provider.close()
