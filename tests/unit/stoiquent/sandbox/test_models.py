from __future__ import annotations

import pytest
from pydantic import ValidationError

from stoiquent.sandbox.models import BindMount, SandboxPolicy, SandboxResult


def test_bind_mount_defaults() -> None:
    mount = BindMount(source="/host/path", target="/container/path")
    assert mount.source == "/host/path"
    assert mount.target == "/container/path"
    assert mount.read_only is True


def test_bind_mount_rejects_empty_source() -> None:
    with pytest.raises(ValidationError, match="source"):
        BindMount(source="", target="/container/path")


def test_bind_mount_rejects_empty_target() -> None:
    with pytest.raises(ValidationError, match="target"):
        BindMount(source="/host/path", target="")


def test_bind_mount_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        BindMount(source="/a", target="/b", unknown="field")


def test_sandbox_policy_defaults() -> None:
    policy = SandboxPolicy()
    assert policy.cpu_seconds == 120.0
    assert policy.memory_mb == 512
    assert policy.disk_mb == 100
    assert policy.max_pids == 64
    assert policy.network == "none"
    assert policy.bind_mounts == []


def test_sandbox_policy_custom_values() -> None:
    policy = SandboxPolicy(
        cpu_seconds=60.0,
        memory_mb=1024,
        disk_mb=200,
        max_pids=128,
        network="host",
        bind_mounts=[
            BindMount(source="/data", target="/mnt/data", read_only=False)
        ],
    )
    assert policy.cpu_seconds == 60.0
    assert policy.memory_mb == 1024
    assert policy.network == "host"
    assert len(policy.bind_mounts) == 1
    assert policy.bind_mounts[0].read_only is False


def test_sandbox_policy_rejects_zero_cpu() -> None:
    with pytest.raises(ValidationError, match="cpu_seconds"):
        SandboxPolicy(cpu_seconds=0)


def test_sandbox_policy_rejects_negative_memory() -> None:
    with pytest.raises(ValidationError, match="memory_mb"):
        SandboxPolicy(memory_mb=-1)


def test_sandbox_policy_rejects_invalid_network() -> None:
    with pytest.raises(ValidationError, match="network"):
        SandboxPolicy(network="bridge")


def test_sandbox_policy_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SandboxPolicy(unknown="field")


def test_sandbox_result_minimal() -> None:
    result = SandboxResult(exit_code=0)
    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.wall_time_seconds == 0.0


def test_sandbox_result_with_output() -> None:
    result = SandboxResult(
        exit_code=1,
        stdout="output",
        stderr="error",
        timed_out=True,
        wall_time_seconds=120.5,
    )
    assert result.exit_code == 1
    assert result.stdout == "output"
    assert result.stderr == "error"
    assert result.timed_out is True
    assert result.wall_time_seconds == 120.5


def test_sandbox_result_rejects_negative_wall_time() -> None:
    with pytest.raises(ValidationError, match="wall_time_seconds"):
        SandboxResult(exit_code=0, wall_time_seconds=-1.0)


def test_sandbox_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SandboxResult(exit_code=0, unknown="field")
