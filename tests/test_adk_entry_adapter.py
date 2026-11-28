"""SLICE-315: entry and runtime paths go through the ADK adapter (ADR-0046 2a)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adk_wall  # noqa: E402

ENTRY_MODULES = frozenset(
    {
        "adk_agent.a2a",
        "adk_agent.cli",
        "adk_agent.console",
        "adk_agent.mcp.server",
        "adk_agent.runtime.execution",
        "adk_agent.runtime.sessions",
    }
)

COMPOSITION_MODULES = frozenset(
    {
        "adk_agent.factory",
        "adk_agent.mcp.client",
        "adk_agent.models",
        "adk_agent.models.gateway_llm",
        "adk_agent.registry.loader",
        "adk_agent.sandbox.agent_channel",
        "adk_agent.sandbox.agent_process",
        "adk_agent.sandbox.agent_worker",
        "adk_agent.sandbox.proxy",
        "adk_agent.sandbox.runner",
        "adk_agent.tools.enforcement",
        "adk_agent.tools.guard",
        "adk_agent.tools.sources",
        "adk_agent.triggers_service",
    }
)


def test_entry_modules_leave_the_wall():
    assert ENTRY_MODULES.isdisjoint(adk_wall.importers()), sorted(
        ENTRY_MODULES & set(adk_wall.importers())
    )


def test_baseline_is_only_composition_and_tools():
    # Slice 2a left these 14 importers; later slices may only remove them.
    assert adk_wall.BASELINE <= COMPOSITION_MODULES


def test_audited_runner_no_longer_fakes_its_class():
    from adk_agent.runtime.audit_proxy import AuditedRunner

    assert "__class__" not in vars(AuditedRunner)


def test_runner_facade_is_a_real_runner():
    from google.adk.runners import Runner

    from adk_agent.adapters.adk.runner import RunnerFacade

    class Target:
        app_name = "demo"
        agent = object()
        session_service = object()

        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def run_async(self, **kwargs):
            self.calls.append(kwargs)
            yield "event"

    target = Target()
    facade = RunnerFacade(target)

    assert isinstance(facade, Runner)
    assert facade.app_name == "demo"
    assert facade.agent is target.agent
    assert facade.session_service is target.session_service

    async def collect() -> list[str]:
        return [event async for event in facade.run_async(user_id="u")]

    assert asyncio.run(collect()) == ["event"]
    assert target.calls == [{"user_id": "u"}]
    assert facade.target is target

    facade.app_name = "other"
    assert target.app_name == "other"
    assert facade.app_name == "other"


def test_a2a_hands_the_executor_a_real_runner(monkeypatch):
    from google.adk.runners import Runner
    from starlette.applications import Starlette

    import adk_agent.a2a as a2a_module
    from adk_agent.runtime.audit_proxy import AuditedRunner

    captured: dict = {}

    def build(agent, **kwargs):
        captured.update(kwargs)
        return Starlette()

    class StubAgent:
        name = "probe"

    monkeypatch.setattr(a2a_module, "_to_a2a", lambda: build)
    a2a_module.build_a2a_app(StubAgent(), runner=object(), require_context=True)

    runner = captured["runner"]
    assert isinstance(runner, Runner)
    assert isinstance(runner.target, AuditedRunner)


def test_session_factories_go_through_the_adapter(tmp_path):
    from google.adk.sessions import InMemorySessionService
    from google.adk.sessions.sqlite_session_service import SqliteSessionService

    from adk_agent.adapters.adk import sessions as adk_sessions
    from adk_agent.runtime.sessions import build_session_service

    assert isinstance(adk_sessions.in_memory_session_service(), InMemorySessionService)
    assert isinstance(build_session_service(), InMemorySessionService)
    sqlite = adk_sessions.sqlite_session_service(str(tmp_path / "sessions.db"))
    assert isinstance(sqlite, SqliteSessionService)


def test_adk_compat_drill_checks_the_runner_gate():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "adk_compat.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS runner-gate" in proc.stdout or "SKIP runner-gate" in proc.stdout
