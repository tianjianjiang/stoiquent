from __future__ import annotations

import logging

from stoiquent.models import SandboxConfig
from stoiquent.sandbox.base import SandboxBackend
from stoiquent.sandbox.noop import NoopBackend

logger = logging.getLogger(__name__)


def detect_backend(config: SandboxConfig) -> SandboxBackend:
    """Detect and return the strongest available sandbox backend.

    For Phase 2, only 'auto' and 'none' are supported (both return NoopBackend).
    Real backends will be added in Phase 5.
    """
    backend_name = config.backend.lower()

    if backend_name in ("auto", "none"):
        logger.info("Using noop sandbox backend (no isolation)")
        return NoopBackend()

    raise SystemExit(
        f"Sandbox backend '{config.backend}' is not yet implemented. "
        "Use 'auto' or 'none' for now."
    )
