#!/usr/bin/env python3
"""Check the ADK surface the adapter depends on (ADR-0046)."""

from __future__ import annotations

import inspect

_CHECKS = []


class SkipCheck(Exception):
    """The optional dependency for this check is not installed."""


def check(name: str):
    def register(fn):
        _CHECKS.append((name, fn))
        return fn

    return register


@check("runner")
def _runner() -> None:
    from google.adk.runners import Runner

    params = set(inspect.signature(Runner.run_async).parameters)
    missing = {"new_message", "user_id", "session_id"} - params
    if missing:
        raise AssertionError(f"Runner.run_async lost {sorted(missing)}")


@check("events")
def _events() -> None:
    from google.adk.events import Event

    fields = set(Event.model_fields)
    missing = {"author", "content", "invocation_id"} - fields
    if missing:
        raise AssertionError(f"Event lost {sorted(missing)}")


@check("mcp")
def _mcp() -> None:
    from google.adk.dependencies import _mcp

    missing = {name for name in ("FastMCP", "Context", "ServerSession") if not hasattr(_mcp, name)}
    if missing:
        raise AssertionError(f"google.adk.dependencies._mcp lost {sorted(missing)}")


@check("agent-to-mcp")
def _agent_to_mcp() -> None:
    from google.adk.tools.mcp_tool import _agent_to_mcp

    missing = {
        name
        for name in ("_build_runner", "_run_agent", "_reap_orphaned_sessions")
        if not hasattr(_agent_to_mcp, name)
    }
    if missing:
        raise AssertionError(f"_agent_to_mcp lost {sorted(missing)}")


@check("runner-gate")
def _runner_gate() -> None:
    """ADK still gates injected runners on ``isinstance(..., Runner)``."""
    from google.adk.runners import Runner

    from adk_agent.adapters.adk.runner import RunnerFacade

    if not isinstance(RunnerFacade(object()), Runner):
        raise AssertionError("RunnerFacade is not a Runner subclass")

    try:
        from google.adk.a2a.executor import a2a_agent_executor
    except ModuleNotFoundError as exc:
        if (exc.name or "").startswith("a2a"):
            raise SkipCheck("a2a-sdk is not installed") from None
        raise

    if not hasattr(a2a_agent_executor.A2aAgentExecutor, "_resolve_runner"):
        raise AssertionError("A2aAgentExecutor lost _resolve_runner; re-read ADR-0046")


@check("a2a-executor")
def _a2a() -> None:
    try:
        from google.adk.a2a.executor import a2a_agent_executor
    except ModuleNotFoundError as exc:
        if (exc.name or "").startswith("a2a"):
            raise SkipCheck("a2a-sdk is not installed") from None
        raise

    if not hasattr(a2a_agent_executor, "A2aAgentExecutor"):
        raise AssertionError("A2aAgentExecutor is gone")


def main() -> int:
    failed = 0
    for name, fn in _CHECKS:
        try:
            fn()
        except SkipCheck as exc:
            print(f"SKIP {name}: {exc}")
        except Exception as exc:  # noqa: BLE001  # every failure is reported the same way
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {name}")
    if failed:
        print(f"{failed} ADK compatibility check(s) failed; re-read ADR-0046")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
