"""Parent side of the agent sandbox worker (ADR-0024)."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import signal
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest

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
    max_model_calls: int = 100


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


async def _stderr_text(task: asyncio.Task[str]) -> str:
    """Collect stderr, bounded even if another process still holds the pipe."""
    try:
        return await asyncio.wait_for(task, timeout=_EXIT_GRACE)
    except asyncio.TimeoutError:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return ""


def _kill(proc: asyncio.subprocess.Process) -> None:
    """Kill the worker and, on POSIX, every process in its session group."""
    if os.name == "posix":
        killpg = getattr(os, "killpg", None)
        sigkill = getattr(signal, "SIGKILL", None)
        if killpg is not None and sigkill is not None:
            with suppress(ProcessLookupError, PermissionError):
                killpg(proc.pid, sigkill)
    if proc.returncode is None:
        with suppress(ProcessLookupError):
            proc.kill()


async def _wait_bounded(proc: asyncio.subprocess.Process) -> None:
    """Never block on ``wait()``: it resolves only after all pipes close."""
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=_EXIT_GRACE)


def _applied_limits(frame: dict[str, Any]) -> dict[str, int]:
    raw = frame.get("applied")
    if raw is None:
        raw = {}
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

    def __init__(
        self,
        limits: AgentSandboxLimits | None = None,
        model: BaseLlm | None = None,
    ) -> None:
        self.limits = limits or AgentSandboxLimits()
        self.model = model

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
        proc: asyncio.subprocess.Process | None = None
        try:
            session: dict[str, Any] = {}
            if os.name == "posix":
                session["start_new_session"] = True
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
                **session,
            )
            stderr_task = asyncio.create_task(_read_stderr(proc.stderr))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.limits.wall_seconds
            try:
                if proc.stdin is None or proc.stdout is None:
                    raise SandboxCrashed("worker pipes are unavailable")
                try:
                    remaining = deadline - loop.time()
                    await asyncio.wait_for(
                        write_frame_async(proc.stdin, request), timeout=remaining
                    )
                except (BrokenPipeError, ConnectionResetError) as exc:
                    raise SandboxCrashed("worker exited before reading the request") from exc
                except FrameError as exc:
                    raise SandboxCrashed(f"request does not fit in one frame: {exc}") from exc
                applied: dict[str, int] = {}
                model_calls = [0]
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    try:
                        frame = await asyncio.wait_for(
                            read_frame_async(proc.stdout), timeout=remaining
                        )
                    except FrameError as exc:
                        if proc.stdin is not None:
                            proc.stdin.close()
                        await self._reap(proc)
                        stderr = await _stderr_text(stderr_task)
                        detail = f": {stderr.strip()[:300]}" if stderr.strip() else ""
                        raise SandboxCrashed(f"worker protocol error: {exc}{detail}") from exc
                    if not isinstance(frame, dict):
                        raise SandboxCrashed("worker sent a non-object frame")
                    kind = frame.get("type")
                    if kind == "limits":
                        applied = _applied_limits(frame)
                        continue
                    if kind == "model":
                        await self._serve_model(frame, proc, deadline, model_calls)
                        continue
                    if kind == "final":
                        if proc.stdin is not None:
                            proc.stdin.close()
                        await self._reap(proc)
                        return SandboxResult(text=str(frame.get("text", "")), limits=applied)
                    if kind == "error":
                        if proc.stdin is not None:
                            proc.stdin.close()
                        await self._reap(proc)
                        raise _error(frame, await _stderr_text(stderr_task))
                    raise SandboxCrashed("worker sent an unknown frame")
            except asyncio.TimeoutError:
                raise SandboxTimeout(f"worker exceeded {self.limits.wall_seconds}s") from None
            finally:
                if proc.stdin is not None and not proc.stdin.is_closing():
                    proc.stdin.close()
                if proc.returncode is None:
                    _kill(proc)
                    await _wait_bounded(proc)
                if not stderr_task.done():
                    stderr_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await stderr_task
        finally:
            if proc is not None and proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
            shutil.rmtree(workdir, ignore_errors=True)

    def _sanitize_model_request(self, data: Any) -> LlmRequest:
        """Trust nothing from the child: fix the model and drop egress overrides."""
        if not isinstance(data, dict):
            raise SandboxCrashed("worker sent an invalid model request")
        payload = dict(data)
        config = payload.get("config")
        if isinstance(config, dict):
            config = dict(config)
            config.pop("http_options", None)
            payload["config"] = config
        payload.pop("live_connect_config", None)
        name = getattr(self.model, "model", None)
        if isinstance(name, str) and name:
            payload["model"] = name
        return LlmRequest.model_validate(payload)

    async def _serve_model(
        self,
        frame: dict[str, Any],
        proc: asyncio.subprocess.Process,
        deadline: float,
        calls: list[int],
    ) -> None:
        call_id = frame.get("id")
        if not isinstance(call_id, int) or proc.stdin is None:
            raise SandboxCrashed("worker sent an invalid model frame")
        if self.model is None:
            await self._reply(
                proc,
                {
                    "type": "model_error",
                    "id": call_id,
                    "message": "model mediation is not configured",
                },
                deadline,
            )
            return
        if calls[0] >= self.limits.max_model_calls:
            await self._reply(
                proc,
                {"type": "model_error", "id": call_id, "message": "model call limit exceeded"},
                deadline,
            )
            return
        calls[0] += 1
        model = self.model
        try:
            try:
                request = self._sanitize_model_request(frame.get("request"))

                async def collect() -> list[dict[str, Any]]:
                    return [
                        item.model_dump(mode="json")
                        async for item in model.generate_content_async(request, stream=False)
                    ]

                remaining = max(deadline - asyncio.get_running_loop().time(), 0.001)
                responses = await asyncio.wait_for(collect(), timeout=remaining)
            except asyncio.TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001
                await self._reply(
                    proc,
                    {"type": "model_error", "id": call_id, "message": type(exc).__name__},
                    deadline,
                )
                return
            await self._reply(
                proc,
                {"type": "model_result", "id": call_id, "responses": responses},
                deadline,
            )
        except asyncio.TimeoutError:
            raise
        except SandboxCrashed:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SandboxCrashed(f"model mediation failed ({type(exc).__name__})") from exc

    @staticmethod
    async def _reply(
        proc: asyncio.subprocess.Process,
        payload: dict[str, Any],
        deadline: float,
    ) -> None:
        if proc.stdin is None:
            raise SandboxCrashed("worker pipes are unavailable")
        remaining = max(deadline - asyncio.get_running_loop().time(), 0.001)
        await asyncio.wait_for(write_frame_async(proc.stdin, payload), timeout=remaining)

    @staticmethod
    async def _reap(proc: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=_EXIT_GRACE)
        except asyncio.TimeoutError:
            _kill(proc)
            await _wait_bounded(proc)
