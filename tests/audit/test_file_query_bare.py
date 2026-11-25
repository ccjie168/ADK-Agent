"""SLICE-282: audit readers accept the bare events written by --audit-file."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import AuditPipeline, FileAuditQuery, JsonlAuditSink, query_events
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

AUTH = {"Authorization": "Bearer secret"}
START = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _event(index: int, *, tenant: str = "t1") -> AuditEvent:
    return AuditEvent(
        event_id=f"e{index}",
        run_id="r1",
        trace_id="tr1",
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="agent.run",
        target="bot",
        status="ok",
        timestamp=START + timedelta(seconds=index),
    )


def _write_bare(path, events) -> None:
    sink = JsonlAuditSink(path)

    async def scenario():
        for event in events:
            await sink.emit(event)

    asyncio.run(scenario())


def _write_chained(path, events) -> None:
    pipeline = AuditPipeline(path)

    async def scenario():
        for event in events:
            await pipeline.append(event)

    asyncio.run(scenario())


def test_query_events_reads_bare_events(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_bare(path, [_event(0), _event(1), _event(2)])

    events = query_events(path, limit=10, order="asc")

    assert [event.event_id for event in events] == ["e0", "e1", "e2"]
    assert query_events(path, limit=10)[-1].event_id == "e0"


def test_query_events_filters_bare_events(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_bare(path, [_event(0), _event(1, tenant="t2"), _event(2)])

    events = query_events(path, tenant="t1", limit=10)

    assert [event.event_id for event in events] == ["e2", "e0"]


def test_query_events_skips_a_half_written_bare_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_bare(path, [_event(0), _event(1)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event_id": "e2", "run_id":')

    events = query_events(path, limit=10)

    assert [event.event_id for event in events] == ["e1", "e0"]


def test_query_events_rejects_a_corrupt_middle_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_bare(path, [_event(0)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_event(2).model_dump_json() + "\n")

    with pytest.raises(ValueError):
        query_events(path, limit=10)


def test_query_events_still_reads_chained_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_chained(path, [_event(0), _event(1)])

    events = query_events(path, limit=10, order="asc")

    assert [event.event_id for event in events] == ["e0", "e1"]


def test_console_audit_lists_its_own_jsonl_file(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path)
    app = build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=["admin"],
        audit_sink=sink,
        audit_query=FileAuditQuery(path),
    )

    async def emit():
        await sink.emit(_event(0))
        await sink.emit(_event(1))

    asyncio.run(emit())
    with TestClient(app) as client:
        response = client.get("/api/audit", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert [item["event_id"] for item in body] == ["e0", "e1"]
