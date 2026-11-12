"""SLICE-035: the audit pipeline service and its HTTP sink."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from adk_agent.audit import AuditPipeline
from adk_agent.audit.http_sink import AuditSinkUnavailable, HttpAuditSink
from adk_agent.audit.service import build_audit_pipeline_app
from adk_agent.core import AgentRef, AuditEvent, AuditRecord, Principal

AUTH = {"Authorization": "Bearer secret"}


class BrokenPipeline:
    async def append(self, event: AuditEvent) -> Any:
        raise RuntimeError("disk full")


def _event() -> AuditEvent:
    return AuditEvent(
        event_id="e1",
        run_id="r1",
        trace_id="tr1",
        tenant="t1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="model.call",
        target="litellm:deepseek",
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _client(tmp_path, *, auth_token: str = "secret") -> tuple[HttpAuditSink, httpx.AsyncClient]:
    app = build_audit_pipeline_app(AuditPipeline(tmp_path / "audit.jsonl"), auth_token="secret")
    http_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://audit")
    return HttpAuditSink("http://audit", auth_token=auth_token, client=http_client), http_client


def test_network_bind_requires_token(tmp_path):
    with pytest.raises(ValueError):
        build_audit_pipeline_app(
            AuditPipeline(tmp_path / "audit.jsonl"), host="0.0.0.0", auth_token=None
        )


def test_healthz_open_and_events_protected(tmp_path):
    app = build_audit_pipeline_app(AuditPipeline(tmp_path / "audit.jsonl"), auth_token="secret")
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/v1/events", json=_event().model_dump(mode="json")).status_code == 401

        response = client.post("/v1/events", json=_event().model_dump(mode="json"), headers=AUTH)
    assert response.status_code == 202
    assert len(response.json()["hash"]) == 64


def test_write_failure_maps_to_502(tmp_path):
    app = build_audit_pipeline_app(BrokenPipeline(), auth_token="secret")
    with TestClient(app) as client:
        response = client.post("/v1/events", json=_event().model_dump(mode="json"), headers=AUTH)
    assert response.status_code == 502
    assert response.json() == {"error": "audit_write_failed"}


def test_client_roundtrip(tmp_path):
    sink, http_client = _client(tmp_path)
    try:
        asyncio.run(sink.emit(_event()))
    finally:
        asyncio.run(http_client.aclose())

    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0]
    record = AuditRecord.model_validate_json(line)
    assert record.event == _event()


def test_client_rejects_bad_token(tmp_path):
    sink, http_client = _client(tmp_path, auth_token="wrong")
    try:
        with pytest.raises(AuditSinkUnavailable):
            asyncio.run(sink.emit(_event()))
    finally:
        asyncio.run(http_client.aclose())
    assert not (tmp_path / "audit.jsonl").exists()
