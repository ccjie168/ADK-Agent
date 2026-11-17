"""Child process entry for the agent sandbox. Do not import this module in-process."""

from __future__ import annotations

import asyncio
import base64
import importlib
import os
import sys
from typing import Any, cast

from ..core import AgentArtifact
from ..registry.loader import load_artifact_agent
from .errors import SandboxError
from .frames import FrameError, read_frame, write_frame
from .guard import install_network_guard
from .policy import SandboxPolicy

_ALLOWED_ENV = ("SYSTEMROOT", "TEMP", "TMP")
_MAX_INPUT = 8000


def _apply_limits(limits: dict[str, Any]) -> dict[str, int]:
    if os.name != "posix":
        return {}
    resource = cast(Any, importlib.import_module("resource"))

    applied: dict[str, int] = {}

    def set_limit(kind: int, key: str, value: int) -> None:
        try:
            resource.setrlimit(kind, (value, value))
        except (ValueError, OSError):
            return
        applied[key] = value

    cpu = limits.get("cpu_seconds")
    if isinstance(cpu, int) and cpu > 0:
        set_limit(resource.RLIMIT_CPU, "cpu_seconds", cpu)
    memory = limits.get("memory_mb")
    if isinstance(memory, int) and memory > 0:
        set_limit(resource.RLIMIT_AS, "memory_mb", memory)
    files = limits.get("open_files")
    if isinstance(files, int) and files > 0:
        set_limit(resource.RLIMIT_NOFILE, "open_files", files)
    size = limits.get("file_bytes")
    if isinstance(size, int) and size > 0:
        set_limit(resource.RLIMIT_FSIZE, "file_bytes", size)
    processes = limits.get("processes")
    if isinstance(processes, int) and processes > 0:
        set_limit(resource.RLIMIT_NPROC, "processes", processes)
    return applied


def _clear_env() -> None:
    allowed = _ALLOWED_ENV if os.name == "nt" else ()
    kept = {name: os.environ[name] for name in allowed if name in os.environ}
    os.environ.clear()
    os.environ.update(kept)


def _is_violation(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, SandboxError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


async def _run(agent: Any, input_text: str) -> str:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    service = InMemorySessionService()
    runner = Runner(app_name=agent.name, agent=agent, session_service=service)
    session = await service.create_session(app_name=agent.name, user_id="sandbox")
    message = types.Content(role="user", parts=[types.Part(text=input_text)])
    text = ""
    async for event in runner.run_async(
        user_id="sandbox", session_id=str(session.id), new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
    return text


def main() -> int:
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    phase = "load"
    try:
        request = read_frame(sys.stdin.buffer)
        if not isinstance(request, dict) or request.get("type") != "run":
            raise FrameError("unexpected request")
        applied = _apply_limits(dict(request.get("limits") or {}))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        install_network_guard(SandboxPolicy(allow_network=False))
        _clear_env()
        write_frame(out, {"type": "limits", "applied": applied})
        artifact = AgentArtifact.model_validate(request["artifact"])
        data = base64.b64decode(str(request["data"]), validate=True)
        input_text = str(request.get("input", ""))[:_MAX_INPUT]
        agent = load_artifact_agent(artifact, data)
        phase = "run"
        text = loop.run_until_complete(_run(agent, input_text))
        loop.close()
        write_frame(out, {"type": "final", "text": text})
        return 0
    except Exception as exc:  # noqa: BLE001
        kind = "violation" if _is_violation(exc) else "crash" if phase == "run" else "load"
        message = f"{type(exc).__name__}: {exc}"[:200]
        write_frame(out, {"type": "error", "kind": kind, "message": message})
        return 2


if __name__ == "__main__":
    sys.exit(main())
