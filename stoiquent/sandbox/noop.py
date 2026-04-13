from __future__ import annotations

import asyncio
import logging
import time

from stoiquent.sandbox.base import SandboxBackend
from stoiquent.sandbox.models import SandboxPolicy, SandboxResult

logger = logging.getLogger(__name__)

_WARNED = False


class NoopBackend(SandboxBackend):
    """Direct execution backend with no isolation.

    Only enforces timeout. Suitable for development and testing.
    """

    async def execute(
        self,
        command: list[str],
        policy: SandboxPolicy,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        global _WARNED  # noqa: PLW0603
        if not _WARNED:
            logger.warning(
                "Running in noop sandbox mode -- no process isolation. "
                "Configure a sandbox backend for production use."
            )
            _WARNED = True

        effective_timeout = timeout if timeout is not None else policy.cpu_seconds
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=env,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin.encode() if stdin else None),
                timeout=effective_timeout,
            )
            wall_time = time.monotonic() - start
            return SandboxResult(
                exit_code=proc.returncode or 0,
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
                wall_time_seconds=wall_time,
            )
        except asyncio.TimeoutError:
            wall_time = time.monotonic() - start
            proc.kill()
            await proc.wait()
            return SandboxResult(
                exit_code=-1,
                stderr="Process timed out",
                timed_out=True,
                wall_time_seconds=wall_time,
            )
        except FileNotFoundError:
            wall_time = time.monotonic() - start
            return SandboxResult(
                exit_code=127,
                stderr=f"Command not found: {command[0]}",
                wall_time_seconds=wall_time,
            )

    async def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "noop"
