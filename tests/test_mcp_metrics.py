"""SLICE-050: MCP runs are counted and the HTTP app exposes metrics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.dependencies._mcp import FastMCP
from google.adk.sessions import InMemorySessionService
from starlette.testclient import TestClient

from adk_agent.core import Principal, QuotaConfig, QuotaExceeded, QuotaPolicy
from adk_agent.mcp.http import build_http_app
from adk_agent.mcp.server import serve_many
from adk_agent.metrics import MetricsRegistry
from adk_agent.runtime.quota import InMemoryQuotaManager

ALICE = Principal(tenant="acme", subject="alice", kind="human")
AUTH = {"Authorization": "Bearer secret"}


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False


class FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [FakePart(text)]


class FakeEvent:
    def __init__(self, text: str) -> None:
        self.content = FakeContent(text)

    def is_final_response(self) -> bool:
        return True


class FakeRunner:
    app_name = "probe"

    def __init__(self) -> None:
        self.session_service = InMemorySessionService()

    async def run_async(self, **kwargs: Any):
        yield FakeEvent("hi")


def _agent() -> LlmAgent:
    return LlmAgent(name="probe", model="gemini-2.5-pro", description="probe", instruction="x")


def _ctx() -> Any:
    state = SimpleNamespace(principal=ALICE)
    request = SimpleNamespace(state=state, headers={})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _patch_adk(monkeypatch) -> None:
    async def fake_run_agent(runner, request, ctx, sessions, created, locks):
        return [event async for event in runner.run_async(user_id="mcp_user", session_id="s1")]

    monkeypatch.setattr("google.adk.tools.mcp_tool._agent_to_mcp._run_agent", fake_run_agent)
    monkeypatch.setattr("mcp.server.mcpserver.server.MCPServer.run", lambda self, *a, **k: None)


def _server(metrics: MetricsRegistry, **kwargs) -> Any:
    return serve_many(
        {"probe": _agent()},
        transport="stdio",
        runner_factory=lambda _agent: FakeRunner(),
        metrics=metrics,
        **kwargs,
    )


def test_serve_many_counts_runs(monkeypatch):
    _patch_adk(monkeypatch)
    metrics = MetricsRegistry()
    tool = _server(metrics)._tool_manager.get_tool("probe")

    asyncio.run(tool.fn("hello", _ctx()))

    text = metrics.render()
    assert 'adk_agent_runs_total{agent="probe",source="mcp",status="ok",tenant="acme"} 1' in text
    assert 'adk_agent_run_duration_seconds_count{agent="probe",tenant="acme"} 1' in text


def test_serve_many_counts_quota_denials(monkeypatch):
    _patch_adk(monkeypatch)
    metrics = MetricsRegistry()
    quota = InMemoryQuotaManager()
    config = QuotaConfig(tenants={"acme": QuotaPolicy(max_runs=1, window_seconds=60)})
    tool = _server(metrics, quota=quota, quota_config=config)._tool_manager.get_tool("probe")

    async def scenario() -> None:
        await tool.fn("hello", _ctx())
        with pytest.raises(QuotaExceeded):
            await tool.fn("again", _ctx())

    asyncio.run(scenario())

    text = metrics.render()
    assert (
        'adk_agent_runs_total{agent="probe",source="mcp",status="denied",tenant="acme"} 1' in text
    )
    assert 'adk_agent_quota_denials_total{limit="max_runs",tenant="acme"} 1' in text


def test_mcp_metrics_endpoint():
    metrics = MetricsRegistry()
    metrics.inc("custom_total", {"k": "v"})
    app = build_http_app(FastMCP(name="probe"), auth_token="secret", metrics=metrics)

    with TestClient(app) as client:
        response = client.get("/metrics", headers=AUTH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'custom_total{k="v"} 1' in response.text


def test_mcp_metrics_require_token():
    app = build_http_app(FastMCP(name="probe"), auth_token="secret", metrics=MetricsRegistry())

    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 401
