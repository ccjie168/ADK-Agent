"""SLICE-046: serve and serve-many wrap the agent run with audit and quota."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

from adk_agent.audit import ListAuditSink
from adk_agent.core import Principal, QuotaConfig, QuotaExceeded, QuotaPolicy
from adk_agent.mcp.server import serve_agent, serve_many
from adk_agent.runtime.quota import InMemoryQuotaManager

ALICE = Principal(tenant="acme", subject="alice", kind="human")
POLICY = QuotaPolicy(max_runs=1, window_seconds=60)


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False


class FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [FakePart(text)]


class FakeEvent:
    def __init__(self, text: str, *, final: bool) -> None:
        self.content = FakeContent(text)
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class FakeRunner:
    app_name = "probe"

    def __init__(self) -> None:
        self.session_service = InMemorySessionService()
        self.calls = 0

    async def run_async(self, **kwargs: Any):
        self.calls += 1
        yield FakeEvent("hi", final=True)


def _agent() -> LlmAgent:
    return LlmAgent(name="probe", model="gemini-2.5-pro", description="probe", instruction="x")


def _ctx(principal: Principal) -> Any:
    state = SimpleNamespace(principal=principal)
    request = SimpleNamespace(state=state)
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _patch_adk(monkeypatch) -> None:
    async def fake_run_agent(runner, request, ctx, sessions, created, locks):
        return [event async for event in runner.run_async(user_id="mcp_user", session_id="s1")]

    monkeypatch.setattr("google.adk.tools.mcp_tool._agent_to_mcp._run_agent", fake_run_agent)
    monkeypatch.setattr("mcp.server.mcpserver.server.MCPServer.run", lambda self, *a, **k: None)


def test_serve_many_wraps_tool(monkeypatch):
    _patch_adk(monkeypatch)
    sink = ListAuditSink()
    runner = FakeRunner()
    quota = InMemoryQuotaManager()
    config = QuotaConfig(tenants={"acme": POLICY})

    server = serve_many(
        {"probe": _agent()},
        transport="stdio",
        runner_factory=lambda _agent: runner,
        audit=sink,
        quota=quota,
        quota_config=config,
    )
    tool = server._tool_manager.get_tool("probe")

    async def scenario() -> None:
        events = await tool.fn("hello", _ctx(ALICE))
        assert len(events) == 1
        with pytest.raises(QuotaExceeded):
            await tool.fn("again", _ctx(ALICE))

    asyncio.run(scenario())

    assert runner.calls == 1
    ok, denied = sink.recent(10)
    assert ok.action == "agent.run"
    assert ok.status == "ok"
    assert ok.tenant == "acme"
    assert ok.target == "probe@dev"
    assert denied.status == "denied"
    assert denied.error_code == "quota_exceeded"


def test_serve_agent_delegates_with_audit(monkeypatch):
    captured: dict = {}

    def fake_serve_many(agents, **kwargs):
        captured.update({"agents": agents, **kwargs})
        return "delegated"

    monkeypatch.setattr("adk_agent.mcp.server.serve_many", fake_serve_many)
    sink = ListAuditSink()

    result = serve_agent(_agent(), transport="stdio", audit=sink)

    assert result == "delegated"
    assert captured["audit"] is sink
    assert list(captured["agents"]) == ["probe"]


def test_serve_agent_delegates_with_quota(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_many",
        lambda agents, **kwargs: captured.update({"agents": agents, **kwargs}) or "delegated",
    )
    quota = InMemoryQuotaManager()
    config = QuotaConfig(tenants={"acme": POLICY})

    serve_agent(_agent(), transport="stdio", quota=quota, quota_config=config)

    assert captured["quota"] is quota
    assert captured["quota_config"] is config


def test_serve_agent_keeps_default_path(monkeypatch):
    calls: dict = {}

    class FakeServer:
        def run(self, *, transport: str) -> None:
            calls["transport"] = transport

    monkeypatch.setattr("google.adk.tools.mcp_tool.to_mcp_server", lambda *a, **k: FakeServer())
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_many", lambda *a, **k: calls.setdefault("delegated", True)
    )

    server = serve_agent(_agent(), transport="stdio")

    assert isinstance(server, FakeServer)
    assert calls["transport"] == "stdio"
    assert "delegated" not in calls
