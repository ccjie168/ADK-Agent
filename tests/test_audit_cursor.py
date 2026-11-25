"""SLICE-301: audit reads order and page by (timestamp, event_id)."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import FileAuditQuery, query_events
from adk_agent.audit.http_sink import HttpAuditQuery
from adk_agent.audit.service import build_audit_pipeline_app
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

STAMP = datetime(2026, 11, 26, tzinfo=timezone.utc)
AUTH = {"Authorization": "Bearer secret"}


def _event(event_id: str, *, stamp: datetime = STAMP) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        run_id=f"r-{event_id}",
        trace_id=f"t-{event_id}",
        tenant="local",
        principal=Principal(tenant="local", subject="u", kind="human"),
        agent_ref=AgentRef(id="bot", version="v1", digest="sha256:x"),
        action="tool.call",
        target="bot@v1",
        status="ok",
        timestamp=stamp,
    )


def _write(tmp_path, events: list[AuditEvent]):
    path = tmp_path / "audit.jsonl"
    path.write_text("\n".join(event.model_dump_json() for event in events) + "\n", encoding="utf-8")
    return path


def test_file_query_orders_same_timestamp_by_event_id(tmp_path):
    events = [_event("e3"), _event("e1"), _event("e4"), _event("e2")]
    path = _write(tmp_path, events)

    newest = query_events(path, limit=2, order="desc")
    oldest = query_events(path, limit=2, order="asc")

    assert [event.event_id for event in newest] == ["e4", "e3"]
    assert [event.event_id for event in oldest] == ["e1", "e2"]


def test_file_query_cursor_pages_same_timestamp(tmp_path):
    events = [_event(f"e{index}") for index in range(1, 6)]
    random.Random(7).shuffle(events)
    path = _write(tmp_path, events)

    first = query_events(path, limit=2, order="desc")
    cursor = (first[-1].timestamp, first[-1].event_id)
    second = query_events(path, limit=2, order="desc", before=cursor)
    cursor = (second[-1].timestamp, second[-1].event_id)
    third = query_events(path, limit=2, order="desc", before=cursor)

    assert [event.event_id for event in first] == ["e5", "e4"]
    assert [event.event_id for event in second] == ["e3", "e2"]
    assert [event.event_id for event in third] == ["e1"]


class _Pipeline:
    path = "unused"


def test_audit_service_cursor_params():
    captured: list[dict] = []

    async def query(**kwargs):
        captured.append(kwargs)
        return []

    app = build_audit_pipeline_app(_Pipeline(), query=query, allow_unauthenticated=True)
    with TestClient(app) as client:
        ok = client.get(
            "/v1/events",
            params={
                "before_timestamp": STAMP.isoformat(),
                "before_event_id": "e4",
                "order": "desc",
            },
        )
        half = client.get("/v1/events", params={"before_timestamp": STAMP.isoformat()})
        asc = client.get(
            "/v1/events",
            params={
                "before_timestamp": STAMP.isoformat(),
                "before_event_id": "e4",
                "order": "asc",
            },
        )

    assert ok.status_code == 200
    assert captured[0]["before"] == (STAMP, "e4")
    assert half.status_code == 400
    assert half.json() == {"error": "invalid_cursor"}
    assert asc.status_code == 400
    assert asc.json() == {"error": "invalid_cursor"}


class _Response:
    status_code = 200

    def __init__(self, events: list[AuditEvent]) -> None:
        self._events = events

    def json(self):
        return {"events": [event.model_dump(mode="json") for event in self._events], "count": 0}


class _RecordingClient:
    def __init__(self, events: list[AuditEvent]) -> None:
        self.calls: list[dict] = []
        self._events = events

    async def get(self, url, params=None, headers=None):
        self.calls.append(dict(params or {}))
        return _Response(self._events)


def test_http_query_sends_cursor():
    client = _RecordingClient([])
    query = HttpAuditQuery("http://127.0.0.1:8799", client=client)

    import asyncio

    asyncio.run(query.events(tenant="local", limit=5, before=(STAMP, "e9")))

    params = client.calls[0]
    assert params["limit"] == 5
    assert params["order"] == "desc"
    assert params["before_timestamp"] == STAMP.isoformat()
    assert params["before_event_id"] == "e9"


def test_console_audit_reads_past_same_timestamp_window(tmp_path):
    events = [_event(f"e{index:04d}") for index in range(1200)]
    random.Random(11).shuffle(events)
    path = _write(tmp_path, events)
    app = build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=["admin"],
        audit_query=FileAuditQuery(path),
    )
    with TestClient(app) as client:
        response = client.get("/api/audit?limit=200", headers=AUTH)

    body = response.json()
    ids = [event["event_id"] for event in body]
    expected = sorted(f"e{index:04d}" for index in range(1000, 1200))

    assert response.status_code == 200
    assert ids == expected
    assert len(set(ids)) == 200
