from __future__ import annotations

from abc import ABC, abstractmethod

from stoiquent.sandbox.models import SandboxPolicy, SandboxResult


class SandboxBackend(ABC):
    @abstractmethod
    async def execute(
        self,
        command: list[str],
        policy: SandboxPolicy,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> SandboxResult: ...

    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    def name(self) -> str: ...
