"""SLICE-062: the audit service exposes a read-only query."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from adk_agent.audit import AuditPipeline, query_events
from adk_agent.audit.service import build_audit_pipeline_app
from adk_agent.core import AgentRef, AuditEvent, Principal

AUTH = {"Authorization": "Bearer secret"}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(
    index: int,
    *,
    tenant: str = "t1",
    trace: str = "tr1",
    run: str = "r1",
    action: str = "model.call",
    status: str = "ok",
) -> AuditEvent:
    return AuditEvent(
        event_id=f"e{index}",
        run_id=run,
        trace_id=trace,
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action=action,
        target="litellm:deepseek",
        status=status,
        timestamp=START + timedelta(seconds=index),
    )


def _write(path, events) -> None:
    pipeline = AuditPipeline(path)

    async def scenario():
        for event in events:
            await pipeline.append(event)

    asyncio.run(scenario())


def test_filters_by_tenant(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1, tenant="t2"), _event(2)])

    events = query_events(path, tenant="t1")

    assert [event.event_id for event in events] == ["e2", "e0"]


def test_order_asc(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1), _event(2)])

    events = query_events(path, order="asc")

    assert [event.event_id for event in events] == ["e0", "e1", "e2"]


def test_limit(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1), _event(2)])

    events = query_events(path, limit=2)

    assert [event.event_id for event in events] == ["e2", "e1"]


def test_field_filters(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(
        path,
        [
            _event(0),
            _event(1, trace="tr2"),
            _event(2, run="r2"),
            _event(3, action="tool.call"),
            _event(4, status="denied"),
        ],
    )

    assert [e.event_id for e in query_events(path, trace_id="tr2")] == ["e1"]
    assert [e.event_id for e in query_events(path, run_id="r2")] == ["e2"]
    assert [e.event_id for e in query_events(path, action="tool.call")] == ["e3"]
    assert [e.event_id for e in query_events(path, status="denied")] == ["e4"]


def test_time_range(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1), _event(2)])

    events = query_events(
        path, since=START + timedelta(seconds=1), until=START + timedelta(seconds=1)
    )

    assert [event.event_id for event in events] == ["e1"]


def test_trailing_partial_line_ignored(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": {"event_id": "half')

    events = query_events(path)

    assert [event.event_id for event in events] == ["e1", "e0"]


def test_partial_line_in_archived_segment_rejected(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0)])
    path.rename(tmp_path / "audit.jsonl.000001")
    with (tmp_path / "audit.jsonl.000001").open("a", encoding="utf-8") as handle:
        handle.write('{"event": {"event_id": "half')

    with pytest.raises(ValueError):
        query_events(path)


def test_reads_segments(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path, max_records=2)

    async def scenario():
        for index in range(5):
            await pipeline.append(_event(index))

    asyncio.run(scenario())

    events = query_events(path, order="asc")

    assert [event.event_id for event in events] == [f"e{index}" for index in range(5)]


def _app(tmp_path, **kwargs) -> TestClient:
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1, tenant="t2")])
    return TestClient(build_audit_pipeline_app(AuditPipeline(path), auth_token="secret", **kwargs))


def test_http_query(tmp_path):
    with _app(tmp_path) as client:
        response = client.get("/v1/events", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert {event["event_id"] for event in body["events"]} == {"e0", "e1"}


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"limit": 0}, "invalid_limit"),
        ({"limit": 1001}, "invalid_limit"),
        ({"order": "sideways"}, "invalid_order"),
        ({"status": "weird"}, "invalid_status"),
        ({"since": "yesterday"}, "invalid_time"),
    ],
)
def test_http_rejects_bad_params(tmp_path, params, error):
    with _app(tmp_path) as client:
        response = client.get("/v1/events", params=params, headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": error}


class _Provider:
    def __init__(self, principals: dict[str, Principal]) -> None:
        self._principals = principals

    async def resolve(self, credential: str) -> Principal:
        return self._principals[credential]


def _oidc_app(tmp_path, principal: Principal) -> TestClient:
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0, tenant="acme"), _event(1, tenant="other")])
    provider = _Provider({"token": principal})
    return TestClient(build_audit_pipeline_app(AuditPipeline(path), auth_token=None, oidc=provider))


def test_oidc_tenant_forbidden(tmp_path):
    principal = Principal(tenant="acme", subject="alice", kind="human")
    with _oidc_app(tmp_path, principal) as client:
        response = client.get(
            "/v1/events", params={"tenant": "other"}, headers={"Authorization": "Bearer token"}
        )

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


def test_oidc_defaults_to_token_tenant(tmp_path):
    principal = Principal(tenant="acme", subject="alice", kind="human")
    with _oidc_app(tmp_path, principal) as client:
        response = client.get("/v1/events", headers={"Authorization": "Bearer token"})

    assert [event["event_id"] for event in response.json()["events"]] == ["e0"]


def test_oidc_admin_cross_tenant(tmp_path):
    principal = Principal(tenant="acme", subject="alice", kind="human", roles=["admin"])
    with _oidc_app(tmp_path, principal) as client:
        response = client.get(
            "/v1/events", params={"tenant": "other"}, headers={"Authorization": "Bearer token"}
        )

    assert response.status_code == 200
    assert [event["event_id"] for event in response.json()["events"]] == ["e1"]
