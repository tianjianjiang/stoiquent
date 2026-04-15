from __future__ import annotations

from pathlib import Path

import pytest

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.models import PersistenceConfig, StreamChunk
from stoiquent.persistence import ConversationStore
from tests.conftest import FakeProvider


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_and_load_with_real_session_messages(tmp_path: Path) -> None:
    """Full round-trip: run agent loop, save conversation, load it back."""
    chunks = [
        StreamChunk(content_delta="The answer is 42."),
        StreamChunk(finish_reason="stop"),
    ]
    provider = FakeProvider(chunks=chunks)
    session = Session(provider=provider)

    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    store.ensure_dirs()

    collected: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        collected.append(chunk)

    await run_agent_loop(session, "What is the meaning of life?", on_chunk)

    assert len(session.messages) == 2
    assert session.messages[0].role == "user"
    assert session.messages[1].role == "assistant"

    store.save_sync(session.id, session.messages)

    record = store.load(session.id)
    assert record is not None
    assert record.id == session.id
    assert record.title == "What is the meaning of life?"
    assert len(record.messages) == 2
    assert record.messages[0].content == "What is the meaning of life?"
    assert record.messages[1].content == "The answer is 42."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_after_multiple_sessions(tmp_path: Path) -> None:
    """Save multiple sessions and verify listing returns all in order."""
    config = PersistenceConfig(data_dir=str(tmp_path))
    store = ConversationStore(config)
    store.ensure_dirs()

    async def noop_chunk(_: StreamChunk) -> None:
        pass

    for i, question in enumerate(["First", "Second", "Third"]):
        chunks = [
            StreamChunk(content_delta=f"Reply {i}"),
            StreamChunk(finish_reason="stop"),
        ]
        provider = FakeProvider(chunks=chunks)
        session = Session(provider=provider)
        await run_agent_loop(session, question, noop_chunk)
        store.save_sync(session.id, session.messages)

    summaries = store.list_conversations()
    assert len(summaries) == 3
    assert summaries[0].title == "Third"
    assert summaries[2].title == "First"
