"""Run a tool handler in a bounded child process."""

from __future__ import annotations

import asyncio
import functools
import inspect
import multiprocessing
import os
import sys
import threading
from collections.abc import Callable
from typing import Any

from .errors import SandboxTimeout, SandboxToolError, SandboxViolation
from .policy import SandboxPolicy
from .worker import child_entry


def _module_importable(handler: Callable[..., Any]) -> bool:
    """Whether a spawn child can import the handler's module by its name."""
    name = getattr(handler, "__module__", "")
    if not name or name == "__main__":
        return False
    module = sys.modules.get(name)
    file = getattr(module, "__file__", None) if module is not None else None
    if not isinstance(file, str):
        return False
    absolute = os.path.abspath(file)
    expected = os.path.join(*name.split(".")) + ".py"
    expected_package = os.path.join(*name.split("."), "__init__.py")
    if not (absolute.endswith(expected) or absolute.endswith(expected_package)):
        return False
    return any(
        bool(entry) and absolute.startswith(os.path.abspath(entry) + os.sep) for entry in sys.path
    )


class ToolSandbox:
    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

    def invoke(
        self,
        handler: Callable[..., Any],
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        kwargs = kwargs or {}
        if os.name == "posix":
            return self._invoke_process(handler, args, kwargs, "fork")
        if not _module_importable(handler):
            return self._invoke_thread(handler, args, kwargs)
        try:
            return self._invoke_process(handler, args, kwargs, "spawn")
        except (AttributeError, TypeError):
            return self._invoke_thread(handler, args, kwargs)
        except Exception as exc:
            if type(exc).__name__ == "PicklingError":
                return self._invoke_thread(handler, args, kwargs)
            raise

    def _invoke_process(
        self,
        handler: Callable[..., Any],
        args: tuple,
        kwargs: dict[str, Any],
        method: str,
    ) -> Any:
        context: Any = multiprocessing.get_context(method)
        parent_conn, child_conn = context.Pipe(duplex=False)
        process = context.Process(
            target=child_entry,
            args=(child_conn, handler, args, kwargs, self.policy.model_dump()),
            daemon=True,
        )
        try:
            process.start()
        except Exception:
            child_conn.close()
            parent_conn.close()
            raise
        child_conn.close()

        try:
            if not parent_conn.poll(self.policy.timeout_seconds):
                raise SandboxTimeout(f"tool call exceeded {self.policy.timeout_seconds}s")
            try:
                message = parent_conn.recv()
            except EOFError as exc:
                raise SandboxViolation("sandbox worker exited without a result") from exc
        finally:
            parent_conn.close()
            process.join(1)
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)

        status, *payload = message
        if status == "ok":
            return payload[0]
        error_code, text = payload
        raise SandboxToolError(error_code, text)

    def _invoke_thread(
        self,
        handler: Callable[..., Any],
        args: tuple,
        kwargs: dict[str, Any],
    ) -> Any:
        box: dict[str, Any] = {}
        done = threading.Event()

        def target() -> None:
            try:
                result = handler(*args, **kwargs)
                if inspect.iscoroutine(result):
                    result = asyncio.run(result)
                elif inspect.isawaitable(result):
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(result)
                    finally:
                        loop.close()
                box["ok"] = result
            except BaseException as exc:
                box["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        if not done.wait(self.policy.timeout_seconds):
            raise SandboxTimeout(f"tool call exceeded {self.policy.timeout_seconds}s")
        if "error" in box:
            error = box["error"]
            raise SandboxToolError(type(error).__name__, str(error))
        return box["ok"]


def sandboxed_callable(handler: Callable[..., Any], sandbox: ToolSandbox) -> Callable[..., Any]:
    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return sandbox.invoke(handler, args, kwargs)

    wrapper.__sandboxed__ = True  # type: ignore[attr-defined]
    return wrapper


def _plain_callable(value: Any) -> bool:
    if not callable(value):
        return False
    from google.adk.tools import BaseTool
    from google.adk.tools.base_toolset import BaseToolset

    return not isinstance(value, (BaseTool, BaseToolset))


def install_tool_sandbox(agent: Any, sandbox: ToolSandbox | None = None) -> None:
    active = sandbox or ToolSandbox()
    tools = getattr(agent, "tools", None)
    if tools:
        agent.tools = [
            tool
            if getattr(tool, "__sandboxed__", False) or not _plain_callable(tool)
            else sandboxed_callable(tool, active)
            for tool in tools
        ]
    for sub in getattr(agent, "sub_agents", None) or ():
        install_tool_sandbox(sub, active)
