"""SLICE-032: append-only JSONL audit sink."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from adk_agent.audit import JsonlAuditSink
from adk_agent.core import AgentRef, AuditEvent, Principal


def _event(action: str) -> AuditEvent:
    return AuditEvent(
        event_id=f"e-{action}",
        run_id="r1",
        trace_id="tr1",
        tenant="t1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action=action,
        target="fake:m",
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_append_writes_one_json_per_event(tmp_path):
    path = tmp_path / "audit" / "events.jsonl"
    sink = JsonlAuditSink(path)

    asyncio.run(sink.emit(_event("model.call")))
    asyncio.run(sink.emit(_event("tool.call")))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)


def test_events_roundtrip(tmp_path):
    path = tmp_path / "events.jsonl"
    sink = JsonlAuditSink(path)
    event = _event("model.call")

    asyncio.run(sink.emit(event))

    stored = AuditEvent.model_validate_json(path.read_text(encoding="utf-8"))
    assert stored == event
