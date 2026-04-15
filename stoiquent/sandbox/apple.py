from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
import uuid
from pathlib import Path

from stoiquent.sandbox.base import SandboxBackend
from stoiquent.sandbox.models import SandboxPolicy, SandboxResult

logger = logging.getLogger(__name__)

_SAFE_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BLOCKED_ENV_KEYS = frozenset({"LD_PRELOAD", "LD_LIBRARY_PATH"})


class AppleContainersBackend(SandboxBackend):
    """Apple Containers backend for macOS 26+.

    Uses the `container` CLI from Apple's open-source container runtime.
    Provides VM-level isolation via Virtualization.framework — stronger
    than OCI containers (no shared kernel).
    """

    def __init__(
        self, runtime_path: str = "/opt/local/bin/container", image: str = "alpine:latest"
    ) -> None:
        self._runtime = runtime_path
        self._image = image

    def _build_run_args(
        self,
        command: list[str],
        policy: SandboxPolicy,
        workdir: str | None,
        env: dict[str, str] | None,
        container_name: str,
        use_stdin: bool = False,
    ) -> list[str]:
        args = [
            self._runtime,
            "run",
            "--rm",
            "--name", container_name,
            "--memory", f"{policy.memory_mb}M",
            "--cpus", "1",
        ]

        if policy.network == "none":
            args.extend(["--network", "none"])

        for mount in policy.bind_mounts:
            resolved = str(Path(mount.source).resolve())
            target = mount.target
            if "," in resolved or "," in target:
                raise ValueError(
                    f"Bind mount paths must not contain commas: {resolved} -> {target}"
                )
            mount_spec = f"type=bind,source={resolved},target={target}"
            if mount.read_only:
                mount_spec += ",readonly"
            args.extend(["--mount", mount_spec])

        if workdir:
            resolved_workdir = str(Path(workdir).resolve())
            if "," in resolved_workdir:
                raise ValueError(f"Workdir must not contain commas: {resolved_workdir}")
            covered_target = None
            for mount in policy.bind_mounts:
                if str(Path(mount.source).resolve()) == resolved_workdir:
                    covered_target = mount.target
                    break
            if covered_target:
                args.extend(["--workdir", covered_target])
            else:
                args.extend([
                    "--mount",
                    f"type=bind,source={resolved_workdir},target=/workspace,readonly",
                ])
                args.extend(["--workdir", "/workspace"])

        if env:
            for key, value in env.items():
                if not _SAFE_ENV_KEY.match(key):
                    raise ValueError(f"Invalid environment variable key: {key!r}")
                if key in _BLOCKED_ENV_KEYS:
                    raise ValueError(f"Blocked environment variable: {key}")
                args.extend(["-e", f"{key}={value}"])

        if use_stdin:
            args.append("-i")

        args.append(self._image)
        args.extend(command)
        return args

    async def execute(
        self,
        command: list[str],
        policy: SandboxPolicy,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        effective_timeout = timeout if timeout is not None else policy.cpu_seconds
        container_name = f"stoiquent-{uuid.uuid4().hex[:12]}"
        run_args = self._build_run_args(
            command, policy, workdir, env, container_name, use_stdin=stdin is not None
        )

        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *run_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin.encode() if stdin else None),
                timeout=effective_timeout,
            )
            wall_time = time.monotonic() - start
            exit_code = proc.returncode
            if exit_code is None:
                logger.error("Container returncode is None after communicate()")
                exit_code = -1
            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
                wall_time_seconds=wall_time,
            )
        except asyncio.TimeoutError:
            wall_time = time.monotonic() - start
            await self._kill_container(container_name)
            return SandboxResult(
                exit_code=-1,
                stderr="Container timed out",
                timed_out=True,
                wall_time_seconds=wall_time,
            )
        except asyncio.CancelledError:
            await self._kill_container(container_name)
            raise
        except FileNotFoundError:
            wall_time = time.monotonic() - start
            return SandboxResult(
                exit_code=127,
                stderr=f"Runtime not found: {self._runtime}",
                wall_time_seconds=wall_time,
            )
        except OSError as e:
            wall_time = time.monotonic() - start
            return SandboxResult(
                exit_code=126,
                stderr=f"Cannot execute container: {e}",
                wall_time_seconds=wall_time,
            )

    async def _kill_container(self, container_name: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._runtime, "kill", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                logger.error(
                    "container kill returned %d for %s: %s",
                    proc.returncode,
                    container_name,
                    stderr.decode(errors="replace").strip() if stderr else "",
                )
        except asyncio.TimeoutError:
            logger.error(
                "Kill command timed out for container %s -- container likely still running",
                container_name,
            )
        except FileNotFoundError:
            logger.error(
                "Runtime binary not found while killing container %s", container_name
            )
        except OSError:
            logger.error(
                "OS error killing container %s", container_name, exc_info=True
            )

    async def is_available(self) -> bool:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [self._runtime, "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.debug("Runtime %s not available", self._runtime, exc_info=True)
            return False

    def name(self) -> str:
        return "apple-containers"
