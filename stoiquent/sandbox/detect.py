from __future__ import annotations

import logging
import os
import shutil
import subprocess

from stoiquent.models import SandboxConfig
from stoiquent.sandbox.base import SandboxBackend
from stoiquent.sandbox.apple import AppleContainersBackend
from stoiquent.sandbox.noop import NoopBackend
from stoiquent.sandbox.oci import OCIBackend

logger = logging.getLogger(__name__)

_RUNTIME_SEARCH_ORDER = ["podman", "finch", "docker"]

_KNOWN_PATHS: dict[str, list[str]] = {
    "container": [
        "/opt/local/bin/container",
        "/usr/local/bin/container",
    ],
    "docker": [
        os.path.expanduser("~/.rd/bin/docker"),
        "/usr/local/bin/docker",
        "/opt/homebrew/bin/docker",
    ],
    "podman": [
        "/usr/local/bin/podman",
        "/opt/homebrew/bin/podman",
    ],
    "finch": [
        "/usr/local/bin/finch",
        "/opt/homebrew/bin/finch",
    ],
}


def _find_runtime(name: str) -> str | None:
    """Find a container runtime binary. Returns absolute path or None."""
    name = name.lower()
    for path in _KNOWN_PATHS.get(name, []):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    found = shutil.which(name)
    return found


def _probe_runtime(path: str, version_flag: str = "version") -> bool:
    """Check if a runtime is functional by running version command."""
    try:
        result = subprocess.run(
            [path, version_flag],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.debug("Runtime probe failed for %s: exit code %d", path, result.returncode)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("Runtime probe failed for %s: %s", path, e)
        return False


def detect_backend(config: SandboxConfig) -> SandboxBackend:
    """Detect and return the strongest available sandbox backend."""
    backend_name = config.backend.lower()

    if backend_name == "none":
        logger.info("Using noop sandbox backend (no isolation)")
        return NoopBackend()

    if backend_name == "apple-containers":
        path = _find_runtime("container")
        if path and _probe_runtime(path, "--version"):
            logger.info("Using Apple Containers backend: %s", path)
            return AppleContainersBackend(path)
        raise SystemExit(
            "Apple Containers not found or not running. "
            "Install via: sudo port install container && container system start"
        )

    if backend_name in ("docker", "podman", "finch"):
        path = _find_runtime(backend_name)
        if path and _probe_runtime(path, "version"):
            logger.info("Using OCI sandbox backend: %s", path)
            return OCIBackend(path)
        raise SystemExit(
            f"Requested backend '{config.backend}' not found or not running."
        )

    if backend_name == "auto":
        preferred = config.container_runtime.lower()
        valid_runtimes = {"auto", *_RUNTIME_SEARCH_ORDER}
        if preferred not in valid_runtimes:
            raise SystemExit(
                f"Unknown container_runtime '{config.container_runtime}'. "
                f"Valid options: {', '.join(sorted(valid_runtimes - {'auto'}))}"
            )
        if preferred != "auto":
            path = _find_runtime(preferred)
            if path and _probe_runtime(path, "version"):
                logger.info("Using preferred OCI runtime: %s", path)
                return OCIBackend(path)
            logger.warning(
                "Preferred runtime '%s' not available, trying others", preferred
            )

        # Tier 1: Apple Containers (VM-level isolation, macOS only)
        apple_path = _find_runtime("container")
        if apple_path and _probe_runtime(apple_path, "--version"):
            logger.info("Auto-detected Apple Containers: %s", apple_path)
            return AppleContainersBackend(apple_path)

        # Tiers 2-3: reserved for Firecracker / gVisor (Linux-only, not yet implemented)

        # Tier 4: OCI container runtimes (Podman/Finch/Docker)
        for rt in _RUNTIME_SEARCH_ORDER:
            path = _find_runtime(rt)
            if path and _probe_runtime(path, "version"):
                logger.info("Auto-detected OCI runtime: %s", path)
                return OCIBackend(path)

        logger.critical(
            "No container runtime found. Falling back to noop sandbox "
            "(NO ISOLATION). Set backend='none' explicitly to suppress this, "
            "or install docker/podman/finch for sandboxed execution."
        )
        return NoopBackend()

    valid = ["auto", "none", "apple-containers", "docker", "podman", "finch"]
    raise SystemExit(
        f"Unknown sandbox backend '{config.backend}'. "
        f"Valid options: {', '.join(valid)}"
    )
