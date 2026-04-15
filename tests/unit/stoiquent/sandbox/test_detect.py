from __future__ import annotations

from unittest.mock import patch

import pytest

from stoiquent.models import SandboxConfig
from stoiquent.sandbox.detect import detect_backend
from stoiquent.sandbox.apple import AppleContainersBackend
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.sandbox.oci import OCIBackend


# --- Existing behavior ---


def test_should_return_noop_for_none() -> None:
    backend = detect_backend(SandboxConfig(backend="none"))
    assert isinstance(backend, NoopBackend)


def test_should_be_case_insensitive() -> None:
    backend = detect_backend(SandboxConfig(backend="None"))
    assert isinstance(backend, NoopBackend)


# --- Auto detection ---


@patch("stoiquent.sandbox.detect._find_runtime", return_value=None)
def test_auto_falls_back_to_noop_when_no_runtime(mock_find) -> None:
    backend = detect_backend(SandboxConfig(backend="auto"))
    assert isinstance(backend, NoopBackend)


@patch("stoiquent.sandbox.detect._probe_runtime", return_value=True)
@patch("stoiquent.sandbox.detect._find_runtime")
def test_auto_returns_oci_when_runtime_available(mock_find_runtime, mock_probe_runtime) -> None:
    # Apple Containers not found, but Docker is
    mock_find_runtime.side_effect = lambda name: (
        "/usr/bin/docker" if name in ("docker", "podman", "finch") else None
    )
    backend = detect_backend(SandboxConfig(backend="auto"))
    assert isinstance(backend, OCIBackend)


@patch("stoiquent.sandbox.detect._probe_runtime", return_value=True)
@patch("stoiquent.sandbox.detect._find_runtime")
def test_auto_respects_preferred_runtime(mock_find, mock_probe) -> None:
    mock_find.side_effect = lambda name: (
        "/usr/local/bin/podman" if name == "podman" else None
    )
    config = SandboxConfig(backend="auto", container_runtime="podman")
    backend = detect_backend(config)
    assert isinstance(backend, OCIBackend)
    assert backend.name() == "oci:podman"


# --- Explicit backend ---


@patch("stoiquent.sandbox.detect._probe_runtime", return_value=True)
@patch("stoiquent.sandbox.detect._find_runtime", return_value="/usr/bin/docker")
def test_explicit_docker_backend(mock_find_runtime, mock_probe_runtime) -> None:
    backend = detect_backend(SandboxConfig(backend="docker"))
    assert isinstance(backend, OCIBackend)


@patch("stoiquent.sandbox.detect._find_runtime", return_value=None)
def test_explicit_backend_not_found_raises(mock_find) -> None:
    with pytest.raises(SystemExit, match="not found or not running"):
        detect_backend(SandboxConfig(backend="docker"))


# --- Unknown backend ---


def test_unknown_backend_raises() -> None:
    with pytest.raises(SystemExit, match="Unknown sandbox backend"):
        detect_backend(SandboxConfig(backend="gvisor"))


# --- Apple Containers ---


@patch("stoiquent.sandbox.detect._probe_runtime", return_value=True)
@patch("stoiquent.sandbox.detect._find_runtime", return_value="/opt/local/bin/container")
def test_explicit_apple_containers(mock_find, mock_probe) -> None:
    backend = detect_backend(SandboxConfig(backend="apple-containers"))
    assert isinstance(backend, AppleContainersBackend)


@patch("stoiquent.sandbox.detect._find_runtime", return_value=None)
def test_explicit_apple_containers_not_found_raises(mock_find) -> None:
    with pytest.raises(SystemExit, match="Apple Containers not found"):
        detect_backend(SandboxConfig(backend="apple-containers"))


@patch("stoiquent.sandbox.detect._probe_runtime", return_value=True)
@patch("stoiquent.sandbox.detect._find_runtime")
def test_auto_prefers_apple_over_oci(mock_find, mock_probe) -> None:
    mock_find.side_effect = lambda name: (
        "/opt/local/bin/container" if name == "container"
        else "/usr/bin/docker" if name == "docker"
        else None
    )
    backend = detect_backend(SandboxConfig(backend="auto"))
    assert isinstance(backend, AppleContainersBackend)
