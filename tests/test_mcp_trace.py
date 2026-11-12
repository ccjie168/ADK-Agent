"""SLICE-047: MCP audit takes the trace id from traceparent."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

from adk_agent.audit import ListAuditSink
from adk_agent.core import Principal
from adk_agent.mcp.server import serve_many

ALICE = Principal(tenant="acme", subject="alice", kind="human")
TRACE = "4bf9" * 8
PARENT = "00f0" * 4


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


def _ctx(traceparent: str | None) -> Any:
    headers = {} if traceparent is None else {"traceparent": traceparent}
    state = SimpleNamespace(principal=ALICE)
    request = SimpleNamespace(state=state, headers=headers)
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _patch_adk(monkeypatch) -> None:
    async def fake_run_agent(runner, request, ctx, sessions, created, locks):
        return [event async for event in runner.run_async(user_id="mcp_user", session_id="s1")]

    monkeypatch.setattr("google.adk.tools.mcp_tool._agent_to_mcp._run_agent", fake_run_agent)
    monkeypatch.setattr("mcp.server.mcpserver.server.MCPServer.run", lambda self, *a, **k: None)


def _run(monkeypatch, traceparent: str | None):
    _patch_adk(monkeypatch)
    sink = ListAuditSink()
    server = serve_many(
        {"probe": _agent()},
        transport="stdio",
        runner_factory=lambda _agent: FakeRunner(),
        audit=sink,
    )
    tool = server._tool_manager.get_tool("probe")
    asyncio.run(tool.fn("hello", _ctx(traceparent)))
    return sink.recent(1)[0]


def test_audit_uses_traceparent(monkeypatch):
    event = _run(monkeypatch, f"00-{TRACE}-{PARENT}-01")

    assert event.trace_id == TRACE


def test_malformed_traceparent_generates(monkeypatch):
    event = _run(monkeypatch, "not-a-traceparent")

    assert event.trace_id != "not-a-traceparent"
    assert re.fullmatch(r"[0-9a-f]{32}", event.trace_id)
