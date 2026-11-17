"""Parent side of the agent sandbox worker (ADR-0024)."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import sys
import tempfile
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
    kept = bytearray()
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        if len(kept) < _MAX_STDERR:
            kept.extend(chunk[: _MAX_STDERR - len(kept)])
    return kept.decode("utf-8", "replace")


def _applied_limits(frame: dict[str, Any]) -> dict[str, int]:
    raw = frame.get("applied") or {}
    if not isinstance(raw, dict):
        raise SandboxCrashed("worker sent an invalid limits frame")
    try:
        return {str(key): int(value) for key, value in raw.items()}
    except (TypeError, ValueError) as exc:
        raise SandboxCrashed("worker sent invalid limit values") from exc


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
        workdir = tempfile.mkdtemp(prefix="adk-agent-sandbox-")
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "adk_agent.sandbox.agent_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
            cwd=workdir,
        )
        stderr_task = asyncio.create_task(_read_stderr(proc.stderr))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.limits.wall_seconds
        try:
            if proc.stdin is None or proc.stdout is None:
                raise SandboxCrashed("worker pipes are unavailable")
            try:
                remaining = deadline - loop.time()
                await asyncio.wait_for(write_frame_async(proc.stdin, request), timeout=remaining)
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise SandboxCrashed("worker exited before reading the request") from exc
            except FrameError as exc:
                raise SandboxCrashed(f"request does not fit in one frame: {exc}") from exc
            finally:
                proc.stdin.close()

            applied: dict[str, int] = {}
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    frame = await asyncio.wait_for(read_frame_async(proc.stdout), timeout=remaining)
                except FrameError as exc:
                    await self._reap(proc)
                    stderr = await stderr_task
                    detail = f": {stderr.strip()[:300]}" if stderr.strip() else ""
                    raise SandboxCrashed(f"worker protocol error: {exc}{detail}") from exc
                if not isinstance(frame, dict):
                    raise SandboxCrashed("worker sent a non-object frame")
                kind = frame.get("type")
                if kind == "limits":
                    applied = _applied_limits(frame)
                    continue
                if kind == "final":
                    await self._reap(proc)
                    return SandboxResult(text=str(frame.get("text", "")), limits=applied)
                if kind == "error":
                    await self._reap(proc)
                    raise _error(frame, await stderr_task)
                raise SandboxCrashed("worker sent an unknown frame")
        except asyncio.TimeoutError:
            raise SandboxTimeout(f"worker exceeded {self.limits.wall_seconds}s") from None
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            if not stderr_task.done():
                stderr_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stderr_task
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    async def _reap(proc: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=_EXIT_GRACE)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
