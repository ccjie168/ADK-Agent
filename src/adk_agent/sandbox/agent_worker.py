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
from .frames import FrameError, read_frame, write_frame
from .guard import install_network_guard, last_violation
from .policy import SandboxPolicy

_ALLOWED_ENV = ("SYSTEMROOT", "TEMP", "TMP")
_MIB = 1024 * 1024


def _apply_limits(limits: dict[str, Any]) -> dict[str, int]:
    if os.name != "posix":
        return {}
    resource = cast(Any, importlib.import_module("resource"))

    applied: dict[str, int] = {}

    def set_limit(kind: int, key: str, value: int, report: Any = int) -> None:
        try:
            resource.setrlimit(kind, (value, value))
            soft, _ = resource.getrlimit(kind)
        except (ValueError, OSError):
            return
        applied[key] = report(soft)

    cpu = limits.get("cpu_seconds")
    if isinstance(cpu, int) and cpu > 0:
        set_limit(resource.RLIMIT_CPU, "cpu_seconds", cpu)
    memory = limits.get("memory_mb")
    if isinstance(memory, int) and memory > 0:
        set_limit(
            resource.RLIMIT_AS,
            "memory_mb",
            memory * _MIB,
            lambda soft: soft // _MIB,
        )
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


def _is_guard_violation(exc: BaseException) -> bool:
    """Only the instance the guard raised counts; artifacts cannot forge it."""
    violation = last_violation()
    if violation is None:
        return False
    stack: list[BaseException | None] = [exc]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if current is violation:
            return True
        stack.append(current.__cause__)
        if not current.__suppress_context__:
            stack.append(current.__context__)
    return False


async def _run(agent: Any, input_text: str, sandbox_channel: Any = None) -> str:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    if sandbox_channel is not None:
        sandbox_channel.start()
    try:
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
    finally:
        if sandbox_channel is not None:
            sandbox_channel.close()


def _sandbox_model(spec: Any = None) -> Any:
    """The parent chooses the model; the artifact's spec is only a label."""
    from .agent_channel import SandboxModel

    return SandboxModel(model="sandboxed")


def _install_model_proxy() -> None:
    import adk_agent
    import adk_agent.models

    adk_agent.build_model = _sandbox_model
    adk_agent.models.build_model = _sandbox_model


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
        install_network_guard(SandboxPolicy(allow_network=False), strict=True)
        _clear_env()
        write_frame(out, {"type": "limits", "applied": applied})
        artifact = AgentArtifact.model_validate(request["artifact"])
        data = base64.b64decode(str(request["data"]), validate=True)
        input_text = str(request.get("input", ""))
        from .agent_channel import SandboxChannel, install_tool_proxy, set_channel

        sandbox_channel = SandboxChannel(sys.stdin.buffer, out)
        set_channel(sandbox_channel)
        _install_model_proxy()
        agent = load_artifact_agent(artifact, data)
        install_tool_proxy(agent, sandbox_channel)
        phase = "run"
        text = loop.run_until_complete(_run(agent, input_text, sandbox_channel))
        loop.close()
        write_frame(out, {"type": "final", "text": text})
        return 0
    except Exception as exc:  # noqa: BLE001
        kind = "violation" if _is_guard_violation(exc) else "crash" if phase == "run" else "load"
        message = f"{type(exc).__name__}: {exc}"[:200]
        write_frame(out, {"type": "error", "kind": kind, "message": message})
        return 2


if __name__ == "__main__":
    sys.exit(main())
