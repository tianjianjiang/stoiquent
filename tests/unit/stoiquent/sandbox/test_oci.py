from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stoiquent.sandbox.models import BindMount, SandboxPolicy, SandboxResult


def _make_backend(runtime_path: str = "/usr/bin/docker", image: str = "python:3.12-slim"):
    from stoiquent.sandbox.oci import OCIBackend

    return OCIBackend(runtime_path, image=image)


# --- _build_run_args ---


def test_build_run_args_default_policy() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    args = backend._build_run_args(["echo", "hi"], policy, None, None, "test-container")

    assert "--rm" in args
    assert "--name" in args
    assert "test-container" in args
    assert "--memory" in args
    assert "512m" in args
    assert "--pids-limit" in args
    assert "64" in args
    assert "--network" in args
    assert "none" in args
    assert "--cpus" in args
    assert "1" in args
    assert "--security-opt=no-new-privileges" in args
    assert "--cap-drop=ALL" in args
    assert "python:3.12-slim" in args
    assert args[-2:] == ["echo", "hi"]


def test_build_run_args_host_network() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(network="host")
    args = backend._build_run_args(["ls"], policy, None, None, "c1")

    idx = args.index("--network")
    assert args[idx + 1] == "host"


def test_build_run_args_bind_mounts() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(bind_mounts=[
        BindMount(source="/data", target="/mnt/data", read_only=True),
        BindMount(source="/output", target="/mnt/out", read_only=False),
    ])
    args = backend._build_run_args(["ls"], policy, None, None, "c1")

    args_str = " ".join(args)
    assert "type=bind,source=/data,target=/mnt/data,readonly" in args_str
    assert "type=bind,source=/output,target=/mnt/out" in args_str
    assert "type=bind,source=/output,target=/mnt/out,readonly" not in args_str


def test_build_run_args_workdir_auto_mount() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    args = backend._build_run_args(["ls"], policy, "/my/workdir", None, "c1")

    args_str = " ".join(args)
    assert "type=bind,source=/my/workdir,target=/workspace" in args_str
    assert "--workdir" in args
    assert "/workspace" in args


def test_build_run_args_env_vars() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    args = backend._build_run_args(
        ["env"], policy, None, {"FOO": "bar", "BAZ": "qux"}, "c1"
    )

    assert "-e" in args
    assert "FOO=bar" in args
    assert "BAZ=qux" in args


def test_build_run_args_rejects_invalid_env_key() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    with pytest.raises(ValueError, match="Invalid environment variable key"):
        backend._build_run_args(["ls"], policy, None, {"bad key": "val"}, "c1")


def test_build_run_args_rejects_blocked_env_key() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    with pytest.raises(ValueError, match="Blocked environment variable"):
        backend._build_run_args(["ls"], policy, None, {"LD_PRELOAD": "/evil.so"}, "c1")


def test_build_run_args_rejects_comma_in_mount_path() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(bind_mounts=[
        BindMount(source="/tmp/foo,bar", target="/mnt/data"),
    ])
    with pytest.raises(ValueError, match="must not contain commas"):
        backend._build_run_args(["ls"], policy, None, None, "c1")


def test_build_run_args_workdir_covered_by_mount_uses_mount_target() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(bind_mounts=[
        BindMount(source="/my/workdir", target="/mnt/data", read_only=True),
    ])
    args = backend._build_run_args(["ls"], policy, "/my/workdir", None, "c1")

    assert "--workdir" in args
    idx = args.index("--workdir")
    assert args[idx + 1] == "/mnt/data"
    # Should NOT have a second auto-mount to /workspace
    args_str = " ".join(args)
    assert "target=/workspace" not in args_str


def test_build_run_args_workdir_auto_mount_is_readonly() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    args = backend._build_run_args(["ls"], policy, "/my/workdir", None, "c1")

    args_str = " ".join(args)
    assert "type=bind,source=" in args_str
    assert "target=/workspace,readonly" in args_str


def test_build_run_args_custom_policy() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(memory_mb=1024, max_pids=128)
    args = backend._build_run_args(["ls"], policy, None, None, "c1")

    assert "1024m" in args
    assert "128" in args


def test_name_includes_runtime() -> None:
    backend = _make_backend("/usr/bin/docker")
    assert backend.name() == "oci:docker"

    backend2 = _make_backend("/usr/local/bin/podman")
    assert backend2.name() == "oci:podman"


# --- execute (mocked subprocess) ---


@pytest.mark.asyncio
async def test_execute_returns_result_on_success() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.execute(["echo", "hello"], policy)

    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.timed_out is False
    assert result.wall_time_seconds > 0


@pytest.mark.asyncio
async def test_execute_handles_timeout() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.returncode = None

    # Mock the kill subprocess too
    mock_kill_proc = AsyncMock()
    mock_kill_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_kill_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", side_effect=[mock_proc, mock_kill_proc]):
        result = await backend.execute(["sleep", "999"], policy, timeout=0.1)

    assert result.timed_out is True
    assert result.exit_code == -1


@pytest.mark.asyncio
async def test_execute_handles_nonzero_exit() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error msg\n"))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.execute(["false"], policy)

    assert result.exit_code == 1
    assert result.stderr == "error msg\n"


# --- is_available ---


@pytest.mark.asyncio
async def test_is_available_when_runtime_works() -> None:
    backend = _make_backend()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        assert await backend.is_available() is True


@pytest.mark.asyncio
async def test_is_available_when_runtime_fails() -> None:
    backend = _make_backend()

    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        assert await backend.is_available() is False
