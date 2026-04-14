from __future__ import annotations

import sys

import pytest

from stoiquent.sandbox.models import SandboxPolicy
from stoiquent.sandbox.noop import NoopBackend


@pytest.mark.asyncio
async def test_should_execute_simple_command() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "print('hello')"],
        SandboxPolicy(),
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.timed_out is False


@pytest.mark.asyncio
async def test_should_capture_stderr() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "import sys; sys.stderr.write('err\\n')"],
        SandboxPolicy(),
    )
    assert "err" in result.stderr


@pytest.mark.asyncio
async def test_should_return_nonzero_exit_code() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "raise SystemExit(42)"],
        SandboxPolicy(),
    )
    assert result.exit_code == 42


@pytest.mark.asyncio
async def test_should_timeout_long_running_command() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        SandboxPolicy(),
        timeout=0.1,
    )
    assert result.timed_out is True
    assert result.exit_code == -1


@pytest.mark.asyncio
async def test_should_handle_command_not_found() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        ["nonexistent-command-12345"],
        SandboxPolicy(),
    )
    assert result.exit_code == 127
    assert "not found" in result.stderr.lower()


@pytest.mark.asyncio
async def test_should_pass_stdin() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
        SandboxPolicy(),
        stdin="hello from stdin",
    )
    assert result.exit_code == 0
    assert "hello from stdin" in result.stdout


@pytest.mark.asyncio
async def test_should_measure_wall_time() -> None:
    backend = NoopBackend()
    result = await backend.execute(
        [sys.executable, "-c", "pass"],
        SandboxPolicy(),
    )
    assert result.wall_time_seconds >= 0


@pytest.mark.asyncio
async def test_should_be_available() -> None:
    backend = NoopBackend()
    assert await backend.is_available() is True


def test_should_have_noop_name() -> None:
    assert NoopBackend().name() == "noop"
