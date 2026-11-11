"""SLICE-016: in-memory audit sink."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from adk_agent.audit import ListAuditSink
from adk_agent.core import AgentRef, AuditEvent, Principal


def _event(index: int) -> AuditEvent:
    return AuditEvent(
        event_id=f"e{index}",
        run_id=f"r{index}",
        trace_id="tr1",
        tenant="t1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        action="agent.run",
        target="support-bot@1.0.0",
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_recent_returns_last_n():
    sink = ListAuditSink(maxlen=3)
    for index in range(5):
        asyncio.run(sink.emit(_event(index)))

    assert [event.event_id for event in sink.recent(2)] == ["e3", "e4"]
    assert len(sink.recent(10)) == 3


def test_rejects_non_positive_maxlen():
    with pytest.raises(ValueError):
        ListAuditSink(maxlen=0)
