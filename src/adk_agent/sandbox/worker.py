"""Child-process entry point. Limits, clears env, guards sockets, runs the handler."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import os
from typing import Any, cast

from .guard import install_network_guard
from .policy import SandboxPolicy


def _apply_limits(policy: SandboxPolicy) -> None:
    if os.name != "posix":
        return
    resource = cast(Any, importlib.import_module("resource"))

    if policy.max_cpu_seconds is not None:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (policy.max_cpu_seconds, policy.max_cpu_seconds),
        )
    if policy.max_memory_mb is not None:
        limit = policy.max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def _clear_env(allowlist: list[str]) -> None:
    kept = {name: os.environ[name] for name in allowlist if name in os.environ}
    os.environ.clear()
    os.environ.update(kept)


def _call_async(handler: Any, args: tuple, kwargs: dict, policy: SandboxPolicy) -> Any:
    result = handler(*args, **kwargs)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # The loop opens its own self-pipe. Priming it before the guard keeps
        # that local socket out of the network policy.
        loop.run_until_complete(asyncio.sleep(0))
        install_network_guard(policy)
        return loop.run_until_complete(result)
    finally:
        result.close()
        loop.close()
        asyncio.set_event_loop(None)


def _call(handler: Any, args: tuple, kwargs: dict, policy: SandboxPolicy) -> Any:
    if inspect.iscoroutinefunction(handler):
        return _call_async(handler, args, kwargs, policy)

    install_network_guard(policy)
    result = handler(*args, **kwargs)
    if inspect.iscoroutine(result):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(asyncio.sleep(0))
            return loop.run_until_complete(result)
        finally:
            result.close()
            loop.close()
            asyncio.set_event_loop(None)
    if inspect.isawaitable(result):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(result)
        finally:
            loop.close()
    return result


def child_entry(
    connection: Any,
    handler: Any,
    args: tuple,
    kwargs: dict,
    policy_data: dict,
) -> None:
    try:
        policy = SandboxPolicy(**policy_data)
        _clear_env(policy.env_allowlist)
        _apply_limits(policy)
        result = _call(handler, args, kwargs, policy)
        try:
            connection.send(("ok", result))
        except Exception as exc:
            connection.send(("error", "SandboxSerializationError", str(exc)))
    except BaseException as exc:
        with contextlib.suppress(Exception):
            connection.send(("error", type(exc).__name__, str(exc)))
    finally:
        connection.close()
