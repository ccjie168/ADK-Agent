"""Parent side of the agent sandbox worker (ADR-0024)."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ..core import AgentArtifact
from .agent import SandboxResult
from .errors import SandboxCrashed, SandboxTimeout, SandboxViolation
from .frames import FrameError, read_frame_async, write_frame_async

_MAX_STDERR = 8192
_EXIT_GRACE = 5.0


@dataclass(frozen=True)
class AgentSandboxLimits:
    wall_seconds: float = 30.0
    cpu_seconds: int = 10
    memory_mb: int = 1024
    open_files: int = 256
    file_bytes: int = 8 * 1024 * 1024
    processes: int | None = None


async def _read_stderr(stream: asyncio.StreamReader | None) -> str:
    if stream is None:
        return ""
    chunks: list[bytes] = []
    total = 0
    while total < _MAX_STDERR:
        chunk = await stream.read(min(4096, _MAX_STDERR - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


def _error(frame: dict[str, Any], stderr: str) -> Exception:
    kind = str(frame.get("kind", ""))
    message = str(frame.get("message", "worker failed"))[:200]
    if kind == "violation":
        return SandboxViolation(message)
    detail = f"{message} ({stderr.strip()[:200]})" if stderr.strip() else message
    return SandboxCrashed(detail)


class ProcessAgentSandbox:
    """Run one artifact in a fresh child process with limits and no network."""

    def __init__(self, limits: AgentSandboxLimits | None = None) -> None:
        self.limits = limits or AgentSandboxLimits()

    def _env(self) -> dict[str, str]:
        if os.name != "nt":
            return {}
        names = ("SYSTEMROOT", "TEMP", "TMP")
        return {name: os.environ[name] for name in names if name in os.environ}

    async def run(self, artifact: AgentArtifact, data: bytes, input_text: str) -> SandboxResult:
        request = {
            "type": "run",
            "artifact": artifact.model_dump(mode="json"),
            "data": base64.b64encode(data).decode("ascii"),
            "input": input_text,
            "limits": {
                "cpu_seconds": self.limits.cpu_seconds,
                "memory_mb": self.limits.memory_mb,
                "open_files": self.limits.open_files,
                "file_bytes": self.limits.file_bytes,
                "processes": self.limits.processes,
            },
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-E",
            "-s",
            "-m",
            "adk_agent.sandbox.agent_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        stderr_task = asyncio.create_task(_read_stderr(proc.stderr))
        try:
            if proc.stdin is None or proc.stdout is None:
                raise SandboxCrashed("worker pipes are unavailable")
            try:
                await write_frame_async(proc.stdin, request)
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise SandboxCrashed("worker exited before reading the request") from exc
            finally:
                proc.stdin.close()

            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.limits.wall_seconds
            applied: dict[str, int] = {}
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    frame = await asyncio.wait_for(read_frame_async(proc.stdout), timeout=remaining)
                except FrameError as exc:
                    await stderr_task
                    raise SandboxCrashed(f"worker protocol error: {exc}") from exc
                if not isinstance(frame, dict):
                    raise SandboxCrashed("worker sent a non-object frame")
                kind = frame.get("type")
                if kind == "limits":
                    applied = {str(k): int(v) for k, v in dict(frame.get("applied") or {}).items()}
                    continue
                if kind == "final":
                    await self._reap(proc)
                    return SandboxResult(text=str(frame.get("text", "")), limits=applied)
                if kind == "error":
                    await self._reap(proc)
                    raise _error(frame, await stderr_task)
                raise SandboxCrashed("worker sent an unknown frame")
        except TimeoutError:
            raise SandboxTimeout(f"worker exceeded {self.limits.wall_seconds}s") from None
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            if not stderr_task.done():
                stderr_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stderr_task

    @staticmethod
    async def _reap(proc: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=_EXIT_GRACE)
        except TimeoutError:
            proc.kill()
            await proc.wait()
