from __future__ import annotations

import pytest

from stoiquent.agent.session import Session
from tests.conftest import FakeProvider


def test_session_starts_with_empty_startup_warnings() -> None:
    """A freshly constructed Session has no queued warnings. Locks the
    default so a future refactor can't accidentally pre-seed the list
    and leak stale warnings across app restarts in the same process."""
    session = Session(provider=FakeProvider())
    assert session.startup_warnings == []


def test_consume_startup_warnings_drains_and_clears() -> None:
    """consume_startup_warnings returns the queue contents and empties
    the stored list in one step — subsequent page renders must not
    replay the same notification to a reconnecting client."""
    session = Session(provider=FakeProvider())
    session.startup_warnings.extend(["first", "second"])

    drained = session.consume_startup_warnings()

    assert drained == ["first", "second"]
    assert session.startup_warnings == []
    assert session.consume_startup_warnings() == []


def test_consume_startup_warnings_returns_snapshot_decoupled_from_queue() -> (
    None
):
    """Mutating the returned list must not mutate the session's own
    queue — consumers commonly iterate the return value while later
    code may append new warnings at runtime."""
    session = Session(provider=FakeProvider())
    session.startup_warnings.append("only")

    drained = session.consume_startup_warnings()
    drained.append("mutated")

    session.startup_warnings.append("runtime-added")
    assert session.startup_warnings == ["runtime-added"]


def test_session_still_rejects_non_positive_iteration_limit() -> None:
    """Regression guard: adding the startup_warnings field must not
    have shifted or disabled the existing __post_init__ validators."""
    with pytest.raises(ValueError, match="iteration_limit must be positive"):
        Session(provider=FakeProvider(), iteration_limit=0)
    with pytest.raises(ValueError, match="tool_timeout must be positive"):
        Session(provider=FakeProvider(), tool_timeout=0.0)
