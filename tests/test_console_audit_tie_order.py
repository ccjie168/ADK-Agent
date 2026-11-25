"""SLICE-286: console audit ties are ordered by event id, not backend direction."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import FileAuditQuery, JsonlAuditSink, ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

AUTH = {"Authorization": "Bearer secret"}
START = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _event(event_id: str, *, second: int = 0) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        run_id="r1",
        trace_id="tr1",
        tenant="local",
        principal=Principal(tenant="local", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="agent.run",
        target="bot",
        status="ok",
        timestamp=START + timedelta(seconds=second),
    )


def _app(*, sink, query=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=["admin"],
        audit_sink=sink,
        audit_query=query,
    )


def _ids(response) -> list[str]:
    return [item["event_id"] for item in response.json()]


def test_console_audit_orders_equal_timestamps_by_event_id():
    sink = ListAuditSink()
    for event_id in ("c", "a", "b"):
        asyncio.run(sink.emit(_event(event_id)))
    with TestClient(_app(sink=sink)) as client:
        response = client.get("/api/audit", headers=AUTH)
    assert response.status_code == 200
    assert _ids(response) == ["a", "b", "c"]


def test_console_audit_ties_agree_between_backends(tmp_path):
    path = tmp_path / "audit.jsonl"
    file_sink = JsonlAuditSink(path)
    memory_sink = ListAuditSink()
    for event_id in ("b", "a"):
        event = _event(event_id)
        asyncio.run(file_sink.emit(event))
        asyncio.run(memory_sink.emit(event))

    with TestClient(_app(sink=memory_sink)) as client:
        memory = client.get("/api/audit", headers=AUTH)
    with TestClient(_app(sink=ListAuditSink(), query=FileAuditQuery(path))) as client:
        file = client.get("/api/audit", headers=AUTH)

    assert _ids(memory) == ["a", "b"]
    assert _ids(file) == ["a", "b"]


def test_console_audit_keeps_distinct_timestamps_in_order():
    sink = ListAuditSink()
    for event_id, second in (("late", 2), ("early", 1)):
        asyncio.run(sink.emit(_event(event_id, second=second)))
    with TestClient(_app(sink=sink)) as client:
        response = client.get("/api/audit", headers=AUTH)
    assert _ids(response) == ["early", "late"]
