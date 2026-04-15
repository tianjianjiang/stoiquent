from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from stoiquent.sandbox.apple import AppleContainersBackend
from stoiquent.sandbox.models import BindMount, SandboxPolicy


def _find_container() -> str | None:
    candidates = ["/opt/local/bin/container", "/usr/local/bin/container"]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("container")


def _container_running(path: str) -> bool:
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


_CONTAINER_PATH = _find_container()
_CONTAINER_AVAILABLE = _CONTAINER_PATH is not None and _container_running(_CONTAINER_PATH)

skip_no_container = pytest.mark.skipif(
    not _CONTAINER_AVAILABLE, reason="Apple Containers not available"
)


@skip_no_container
@pytest.mark.integration
@pytest.mark.asyncio
async def test_apple_echo_command() -> None:
    backend = AppleContainersBackend(_CONTAINER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(["echo", "hello from apple"], policy, timeout=30)

    assert result.exit_code == 0
    assert "hello from apple" in result.stdout


@skip_no_container
@pytest.mark.integration
@pytest.mark.asyncio
async def test_apple_timeout_kills_container() -> None:
    backend = AppleContainersBackend(_CONTAINER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(["sleep", "60"], policy, timeout=3)

    assert result.timed_out is True
    assert result.exit_code == -1


@skip_no_container
@pytest.mark.integration
@pytest.mark.asyncio
async def test_apple_stdin_piped() -> None:
    backend = AppleContainersBackend(_CONTAINER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(
        ["cat"], policy, stdin="apple-input", timeout=30
    )

    assert result.exit_code == 0
    assert "apple-input" in result.stdout


@skip_no_container
@pytest.mark.integration
@pytest.mark.asyncio
async def test_apple_bind_mount_readable(tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("apple-mount-data")
    test_file.chmod(0o644)
    tmp_path.chmod(0o755)

    backend = AppleContainersBackend(_CONTAINER_PATH, image="alpine:latest")
    policy = SandboxPolicy(bind_mounts=[
        BindMount(source=str(tmp_path), target="/mnt/data", read_only=True),
    ])
    result = await backend.execute(["cat", "/mnt/data/test.txt"], policy, timeout=30)

    assert result.exit_code == 0
    assert "apple-mount-data" in result.stdout


@skip_no_container
@pytest.mark.integration
@pytest.mark.asyncio
async def test_apple_nonzero_exit() -> None:
    backend = AppleContainersBackend(_CONTAINER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(["false"], policy, timeout=30)

    assert result.exit_code != 0
