from __future__ import annotations

from stoiquent.sandbox.models import SandboxPolicy


def default_policy() -> SandboxPolicy:
    return SandboxPolicy()


def merge_policy(
    base: SandboxPolicy, overrides: dict[str, object]
) -> SandboxPolicy:
    base_data = base.model_dump()
    base_data.update(overrides)
    return SandboxPolicy(**base_data)
