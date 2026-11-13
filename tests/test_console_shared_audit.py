"""SLICE-063: the console reads and writes a shared audit store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.audit import (
    AuditPipeline,
    AuditQueryUnavailable,
    FileAuditQuery,
    HttpAuditQuery,
)
from adk_agent.audit.http_sink import HttpAuditSink
from adk_agent.audit.jsonl import JsonlAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

AUTH = {"Authorization": "Bearer secret"}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(index: int, tenant: str = "t1") -> AuditEvent:
    return AuditEvent(
        event_id=f"e{index}",
        run_id=f"r{index}",
        trace_id=f"tr{index}",
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="agent.run",
        target="bot@v1",
        status="ok",
        timestamp=START + timedelta(seconds=index),
    )


def _write(path, events) -> None:
    pipeline = AuditPipeline(path)

    async def scenario():
        for event in events:
            await pipeline.append(event)

    asyncio.run(scenario())


def test_file_query(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0), _event(1, tenant="t2"), _event(2)])
    query = FileAuditQuery(path)

    events = asyncio.run(query.events(tenant="t1", limit=10))
    limited = asyncio.run(query.events(tenant="t1", limit=1))

    assert [event.event_id for event in events] == ["e2", "e0"]
    assert [event.event_id for event in limited] == ["e2"]


class _Response:
    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.response


def test_http_query():
    payload = {"events": [_event(0).model_dump(mode="json")], "count": 1}
    client = _Client(_Response(200, payload))
    query = HttpAuditQuery("http://audit:8000", auth_token="secret", client=client)

    events = asyncio.run(query.events(tenant="acme", limit=50))

    assert [event.event_id for event in events] == ["e0"]
    call = client.calls[0]
    assert call["url"] == "http://audit:8000/v1/events"
    assert call["params"] == {"tenant": "acme", "limit": 50, "order": "desc"}
    assert call["headers"] == {"Authorization": "Bearer secret"}


def test_http_query_failure():
    query = HttpAuditQuery("http://audit:8000", client=_Client(_Response(500, {})))

    with pytest.raises(AuditQueryUnavailable):
        asyncio.run(query.events(tenant=None, limit=10))


class _RecordingQuery:
    def __init__(self, events=None, error: Exception | None = None) -> None:
        self._events = list(events or [])
        self._error = error
        self.calls: list[tuple[str | None, int]] = []

    async def events(self, *, tenant, limit):
        self.calls.append((tenant, limit))
        if self._error is not None:
            raise self._error
        return list(self._events)


class _Provider:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self.principal


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def test_console_reads_from_query():
    query = _RecordingQuery([_event(0), _event(1, tenant="t2")])
    app = build_console_app(_agents(), auth_token="secret", audit_query=query)

    with TestClient(app) as client:
        response = client.get("/api/audit?limit=10", headers=AUTH)

    assert response.status_code == 200
    assert [event["event_id"] for event in response.json()] == ["e0", "e1"]
    assert query.calls == [(None, 1000)]


def test_console_scopes_tenant():
    query = _RecordingQuery([_event(0, tenant="acme"), _event(1, tenant="other")])
    principal = Principal(tenant="acme", subject="alice", kind="human")
    app = build_console_app(
        _agents(), auth_token=None, oidc=_Provider(principal), audit_query=query
    )

    with TestClient(app) as client:
        response = client.get("/api/audit", headers={"Authorization": "Bearer token"})

    assert query.calls == [("acme", 1000)]
    assert [event["event_id"] for event in response.json()] == ["e0"]


def test_console_admin_query():
    query = _RecordingQuery([_event(0)])
    principal = Principal(tenant="acme", subject="admin", kind="human", roles=["admin"])
    app = build_console_app(
        _agents(), auth_token=None, oidc=_Provider(principal), audit_query=query
    )

    with TestClient(app) as client:
        client.get("/api/audit", headers={"Authorization": "Bearer token"})

    assert query.calls == [(None, 1000)]


def test_console_reads_jsonl_sink_without_query(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, [_event(0)])
    app = build_console_app(_agents(), auth_token="secret", audit_sink=JsonlAuditSink(path))

    with TestClient(app) as client:
        response = client.get("/api/audit", headers=AUTH)

    assert [event["event_id"] for event in response.json()] == ["e0"]


def test_console_maps_outage():
    query = _RecordingQuery(error=AuditQueryUnavailable("down"))
    app = build_console_app(_agents(), auth_token="secret", audit_query=query)

    with TestClient(app) as client:
        audit = client.get("/api/audit", headers=AUTH)
        runs = client.get("/api/runs", headers=AUTH)

    assert audit.status_code == 502
    assert audit.json() == {"error": "audit_unavailable"}
    assert runs.status_code == 502


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


def test_cli_wires_audit_url(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(
        ["console", "--agents", _agents_file(tmp_path), "--audit-url", "http://127.0.0.1:8000"]
    )

    assert isinstance(captured["audit_sink"], HttpAuditSink)
    assert isinstance(captured["audit_query"], HttpAuditQuery)


def test_cli_wires_audit_file(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))
    path = tmp_path / "audit.jsonl"

    cli.main(["console", "--agents", _agents_file(tmp_path), "--audit-file", str(path)])

    assert isinstance(captured["audit_sink"], JsonlAuditSink)
    assert isinstance(captured["audit_query"], FileAuditQuery)


def test_cli_requires_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                _agents_file(tmp_path),
                "--audit-url",
                "http://10.0.0.5:8000",
            ]
        )

    assert exc.value.code == 1
    assert "token" in capsys.readouterr().err
