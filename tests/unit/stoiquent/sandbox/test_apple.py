from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stoiquent.sandbox.apple import AppleContainersBackend
from stoiquent.sandbox.models import BindMount, SandboxPolicy, SandboxResult


def _make_backend(
    runtime_path: str = "/opt/local/bin/container", image: str = "alpine:latest"
) -> AppleContainersBackend:
    return AppleContainersBackend(runtime_path, image=image)


# --- _build_run_args ---


def test_build_run_args_default_policy() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    args = backend._build_run_args(["echo", "hi"], policy, None, None, "test-c")

    assert "--rm" in args
    assert "--name" in args
    assert "test-c" in args
    assert "--memory" in args
    assert "512M" in args
    assert "--cpus" in args
    assert "1" in args
    assert "--network" in args
    assert "none" in args
    assert "alpine:latest" in args
    assert args[-2:] == ["echo", "hi"]
    # Apple Containers: no --pids-limit, no --cap-drop, no --security-opt
    assert "--pids-limit" not in args
    assert "--cap-drop=ALL" not in args
    assert "--security-opt=no-new-privileges" not in args


def test_build_run_args_host_network() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(network="host")
    args = backend._build_run_args(["ls"], policy, None, None, "c1")

    # host network: no --network flag added (Apple Containers default is host)
    assert "--network" not in args


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
    assert "target=/workspace,readonly" in args_str
    assert "--workdir" in args


def test_build_run_args_workdir_covered_by_mount() -> None:
    backend = _make_backend()
    policy = SandboxPolicy(bind_mounts=[
        BindMount(source="/my/workdir", target="/mnt/work", read_only=True),
    ])
    args = backend._build_run_args(["ls"], policy, "/my/workdir", None, "c1")

    idx = args.index("--workdir")
    assert args[idx + 1] == "/mnt/work"


def test_build_run_args_env_vars() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    args = backend._build_run_args(
        ["env"], policy, None, {"FOO": "bar"}, "c1"
    )
    assert "-e" in args
    assert "FOO=bar" in args


def test_build_run_args_rejects_invalid_env_key() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    with pytest.raises(ValueError, match="Invalid environment variable key"):
        backend._build_run_args(["ls"], policy, None, {"bad key": "v"}, "c1")


def test_build_run_args_rejects_blocked_env_key() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()
    with pytest.raises(ValueError, match="Blocked environment variable"):
        backend._build_run_args(["ls"], policy, None, {"LD_PRELOAD": "/x"}, "c1")


def test_name() -> None:
    backend = _make_backend()
    assert backend.name() == "apple-containers"


# --- execute (mocked) ---


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


@pytest.mark.asyncio
async def test_execute_handles_timeout() -> None:
    backend = _make_backend()
    policy = SandboxPolicy()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.returncode = None

    mock_kill = AsyncMock()
    mock_kill.communicate = AsyncMock(return_value=(b"", b""))
    mock_kill.returncode = 0

    with patch("asyncio.create_subprocess_exec", side_effect=[mock_proc, mock_kill]):
        result = await backend.execute(["sleep", "999"], policy, timeout=0.1)

    assert result.timed_out is True
    assert result.exit_code == -1


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
