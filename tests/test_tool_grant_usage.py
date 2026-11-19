"""SLICE-082: tool call audit carries the policy version and usage aggregates."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from google.adk.tools import BaseTool

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Invocation, Principal, ToolGrant
from adk_agent.core.context import reset_invocation, set_invocation
from adk_agent.tools import GrantPolicyEngine, ToolGuard

AUTH = {"Authorization": "Bearer secret"}
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + "a" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class FakeContext:
    function_call_id = "call-1"


class FakeTool(BaseTool):
    def __init__(self, name: str = "crm.read") -> None:
        super().__init__(name=name, description="fake tool")


class FakeOverlay:
    async def active(self, tenant, agent_id, version, digest, tool_id, now=None):
        return True


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1.0.0", digest=DIGEST),
        input="hi",
    )


def _run(guard: ToolGuard, *, deny: bool = False) -> None:
    async def scenario() -> None:
        token = set_invocation(_invocation())
        try:
            await guard.before(FakeTool(), {}, FakeContext())
            if not deny:
                await guard.after(FakeTool(), {}, FakeContext(), "ok")
        finally:
            reset_invocation(token)

    asyncio.run(scenario())


def test_allowed_event_version():
    audit = FakeAudit()
    guard = ToolGuard(GrantPolicyEngine([ToolGrant(tool_id="crm.read")]), audit=audit)

    _run(guard)

    [event] = audit.events
    assert event.status == "ok"
    assert event.policy_version == "grants-v1"


def test_denied_event_version():
    audit = FakeAudit()
    guard = ToolGuard(GrantPolicyEngine([]), audit=audit)

    _run(guard, deny=True)

    [event] = audit.events
    assert event.status == "denied"
    assert event.policy_version == "grants-v1"


def test_temporary_grant_version():
    audit = FakeAudit()
    guard = ToolGuard(GrantPolicyEngine([], overlay=FakeOverlay()), audit=audit)

    _run(guard)

    [event] = audit.events
    assert event.status == "ok"
    assert event.policy_version == "grants-v2"


def _event(tenant: str, target: str, status: str, version: str | None) -> AuditEvent:
    return AuditEvent(
        event_id="e1",
        run_id="r1",
        trace_id="tr1",
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1.0.0", digest=DIGEST),
        action="tool.call",
        target=target,
        status=status,
        policy_version=version,
        timestamp=NOW,
    )


def _app(sink: ListAuditSink, roles=("admin",)):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        audit_sink=sink,
    )


def test_usage_aggregates():
    sink = ListAuditSink()
    for event in (
        _event("local", "crm.read", "ok", "grants-v1"),
        _event("local", "crm.read", "ok", "grants-v2"),
        _event("local", "crm.read", "denied", "grants-v1"),
        _event("local", "crm.export", "ok", "grants-v2"),
    ):
        asyncio.run(sink.emit(event))
    with TestClient(_app(sink)) as client:
        response = client.get("/api/tool-grants/usage?tenant=local", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == [
        {"tool_id": "crm.export", "allowed": 1, "denied": 0, "temporary": 1},
        {"tool_id": "crm.read", "allowed": 2, "denied": 1, "temporary": 1},
    ]


def test_usage_tenant_scope():
    sink = ListAuditSink()
    for event in (
        _event("local", "crm.read", "ok", "grants-v1"),
        _event("other", "crm.read", "ok", "grants-v1"),
    ):
        asyncio.run(sink.emit(event))
    with TestClient(_app(sink, roles=["operator"])) as client:
        response = client.get("/api/tool-grants/usage", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == [{"tool_id": "crm.read", "allowed": 1, "denied": 0, "temporary": 0}]
