from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from stoiquent.sandbox.models import BindMount, SandboxPolicy
from stoiquent.sandbox.oci import OCIBackend


def _find_docker() -> str | None:
    """Find a working Docker runtime for integration tests."""
    candidates = [
        os.path.expanduser("~/.rd/bin/docker"),
        "/usr/local/bin/docker",
        "/opt/homebrew/bin/docker",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("docker")


def _docker_running(path: str) -> bool:
    try:
        result = subprocess.run(
            [path, "version"], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


_DOCKER_PATH = _find_docker()
_DOCKER_AVAILABLE = _DOCKER_PATH is not None and _docker_running(_DOCKER_PATH)

skip_no_docker = pytest.mark.skipif(
    not _DOCKER_AVAILABLE, reason="Docker not available or not running"
)


@skip_no_docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_oci_echo_command() -> None:
    backend = OCIBackend(_DOCKER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(["echo", "hello"], policy, timeout=30)

    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


@skip_no_docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_oci_timeout_kills_container() -> None:
    backend = OCIBackend(_DOCKER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(["sleep", "60"], policy, timeout=2)

    assert result.timed_out is True
    assert result.exit_code == -1


@skip_no_docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_oci_bind_mount_readable(tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("mount-test-data")
    # Make file world-readable so container (cap-drop=ALL) can read it
    test_file.chmod(0o644)
    tmp_path.chmod(0o755)

    backend = OCIBackend(_DOCKER_PATH, image="alpine:latest")
    policy = SandboxPolicy(bind_mounts=[
        BindMount(source=str(tmp_path), target="/mnt/data", read_only=True),
    ])
    result = await backend.execute(["cat", "/mnt/data/test.txt"], policy, timeout=30)

    assert result.exit_code == 0
    assert "mount-test-data" in result.stdout


@skip_no_docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_oci_stdin_piped() -> None:
    backend = OCIBackend(_DOCKER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(
        ["cat"], policy, stdin="piped-input", timeout=30
    )

    assert result.exit_code == 0
    assert "piped-input" in result.stdout


@skip_no_docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_oci_nonzero_exit() -> None:
    backend = OCIBackend(_DOCKER_PATH, image="alpine:latest")
    policy = SandboxPolicy()
    result = await backend.execute(["false"], policy, timeout=30)

    assert result.exit_code != 0
