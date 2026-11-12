"""SLICE-045: the console lists orchestration plans by trace."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

UTC = timezone.utc
AUTH = {"Authorization": "Bearer secret"}
_START = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _event(
    trace_id: str,
    action: str,
    at: datetime,
    *,
    tenant: str = "local",
    status: str = "ok",
    error_code: str | None = None,
    target: str = "step-a",
    latency_ms: int | None = None,
    cost_usd: float | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=f"{trace_id}-{action}-{at.isoformat()}",
        run_id=f"run-{trace_id}",
        trace_id=trace_id,
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="svc", kind="service"),
        agent_ref=AgentRef(id="flow", version="1.0.0", digest="d" * 64),
        action=action,
        target=target,
        status=status,
        error_code=error_code,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        timestamp=at,
    )


def _seed(sink: ListAuditSink, events: list[AuditEvent]) -> None:
    async def run() -> None:
        for event in events:
            await sink.emit(event)

    asyncio.run(run())


def _client(sink: ListAuditSink, *, roles: list[str] | None = None) -> TestClient:
    return TestClient(
        build_console_app(
            _agents(),
            auth_token="secret",
            roles=roles,
            audit_sink=sink,
        )
    )


def _trace_one(*, tenant: str = "local") -> list[AuditEvent]:
    return [
        _event("t1", "orchestration.step", _START, tenant=tenant),
        _event("t1", "orchestration.step", _START + timedelta(seconds=1), tenant=tenant),
        _event("t1", "orchestration.approval", _START + timedelta(seconds=2), tenant=tenant),
        _event(
            "t1",
            "orchestration.run",
            _START + timedelta(seconds=3),
            tenant=tenant,
            target="flow@1.0.0",
            latency_ms=120,
            cost_usd=0.001,
        ),
    ]


def _trace_two() -> list[AuditEvent]:
    at = _START + timedelta(hours=1)
    return [
        _event("t2", "orchestration.step", at),
        _event(
            "t2",
            "orchestration.run",
            at + timedelta(seconds=1),
            status="error",
            error_code="approval_timeout",
            target="flow@1.0.0",
        ),
    ]


def test_plans_group_by_trace():
    sink = ListAuditSink()
    _seed(sink, _trace_one() + _trace_two())
    with _client(sink) as client:
        response = client.get("/api/plans", headers=AUTH)

    assert response.status_code == 200
    plans = response.json()
    assert [plan["trace_id"] for plan in plans] == ["t2", "t1"]

    plan = plans[1]
    assert plan["plan_id"] == "flow@1.0.0"
    assert plan["agent_id"] == "flow"
    assert plan["tenant"] == "local"
    assert plan["status"] == "ok"
    assert plan["steps"] == 2
    assert plan["approvals"] == 1
    assert plan["latency_ms"] == 120
    assert plan["cost_usd"] == 0.001
    assert plan["started_at"] == _START.isoformat()
    assert plan["last_at"] == (_START + timedelta(seconds=3)).isoformat()

    failed = plans[0]
    assert failed["status"] == "error"
    assert failed["error_code"] == "approval_timeout"


def test_plans_filter_by_tenant():
    sink = ListAuditSink()
    _seed(sink, _trace_one(tenant="local") + _trace_one(tenant="other"))
    with _client(sink, roles=["viewer"]) as client:
        response = client.get("/api/plans", headers=AUTH)

    assert {plan["tenant"] for plan in response.json()} == {"local"}


def test_plans_limit_clamped():
    sink = ListAuditSink()
    events = []
    for index in range(3):
        at = _START + timedelta(seconds=index)
        events.append(_event(f"t{index}", "orchestration.run", at, target="flow@1.0.0"))
    _seed(sink, events)
    with _client(sink) as client:
        one = client.get("/api/plans?limit=0", headers=AUTH)
        all_three = client.get("/api/plans?limit=999", headers=AUTH)

    assert len(one.json()) == 1
    assert len(all_three.json()) == 3


def test_plans_empty():
    with _client(ListAuditSink()) as client:
        response = client.get("/api/plans", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []
