from __future__ import annotations

import pytest

from stoiquent.models import SandboxConfig
from stoiquent.sandbox.detect import detect_backend
from stoiquent.sandbox.noop import NoopBackend


def test_should_return_noop_for_auto() -> None:
    backend = detect_backend(SandboxConfig(backend="auto"))
    assert isinstance(backend, NoopBackend)


def test_should_return_noop_for_none() -> None:
    backend = detect_backend(SandboxConfig(backend="none"))
    assert isinstance(backend, NoopBackend)


def test_should_raise_for_unsupported_backend() -> None:
    with pytest.raises(SystemExit, match="not yet implemented"):
        detect_backend(SandboxConfig(backend="podman"))


def test_should_be_case_insensitive() -> None:
    backend = detect_backend(SandboxConfig(backend="Auto"))
    assert isinstance(backend, NoopBackend)
