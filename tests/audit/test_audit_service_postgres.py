"""SLICE-097: the audit service and console read and write the Postgres store."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from adk_agent.audit import PostgresAuditQuery, PostgresAuditSink, query_audit_records
from adk_agent.audit.service import build_audit_pipeline_app
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")

AUTH = {"Authorization": "Bearer secret"}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _tenant() -> str:
    return "t" + uuid.uuid4().hex[:12]


def _event(
    index: int,
    *,
    tenant: str,
    action: str = "agent.run",
    status: str = "ok",
    trace: str | None = None,
    run: str | None = None,
    at: datetime | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=f"{tenant}-e{index}",
        run_id=run or f"r{index}",
        trace_id=trace or f"tr{index}",
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action=action,
        target="bot@v1",
        status=status,
        timestamp=at or (START + timedelta(seconds=index)),
    )


def _connect():
    import asyncpg

    return asyncpg.connect(_LIVE_URL)


def _delete(*tenants: str) -> None:
    async def scenario():
        conn = await _connect()
        try:
            await conn.execute(
                "DELETE FROM adk_audit_records WHERE tenant = ANY($1::text[])",
                list(tenants),
            )
        finally:
            await conn.close()

    asyncio.run(scenario())


def _rows(tenant: str):
    async def scenario():
        conn = await _connect()
        try:
            return await conn.fetch(
                "SELECT sequence, prev_hash, hash, signature, kid, event "
                "FROM adk_audit_records WHERE tenant = $1 ORDER BY sequence",
                tenant,
            )
        finally:
            await conn.close()

    return asyncio.run(scenario())


class _Provider:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self.principal


@_live
@_needs_driver
def test_service_db_roundtrip():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)

    async def scenario():
        app = build_audit_pipeline_app(
            sink,
            auth_token="secret",
            query=lambda **kwargs: query_audit_records(_LIVE_URL, **kwargs),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://audit") as client:
            event = _event(0, tenant=tenant)
            response = await client.post(
                "/v1/events", json=event.model_dump(mode="json"), headers=AUTH
            )
            assert response.status_code == 202
            posted_hash = response.json()["hash"]

            got = await client.get("/v1/events", params={"tenant": tenant}, headers=AUTH)
            assert got.status_code == 200
            payload = got.json()
        await sink.aclose()
        return posted_hash, payload

    try:
        posted_hash, payload = asyncio.run(scenario())

        rows = _rows(tenant)
        assert len(rows) == 1
        assert rows[0]["hash"] == posted_hash
        assert [e["event_id"] for e in payload["events"]] == [f"{tenant}-e0"]
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_service_db_tenant_binding():
    tenant_a = _tenant()
    tenant_b = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)

    async def write():
        await sink.emit(_event(0, tenant=tenant_a, action="model.call"))
        await sink.emit(_event(1, tenant=tenant_a, action="tool.call", status="denied"))
        await sink.emit(_event(0, tenant=tenant_b, action="model.call"))
        await sink.aclose()

    async def read():
        provider = _Provider(Principal(tenant=tenant_a, subject="alice", kind="human"))
        app = build_audit_pipeline_app(
            PostgresAuditSink(_LIVE_URL),
            oidc=provider,
            query=lambda **kwargs: query_audit_records(_LIVE_URL, **kwargs),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://audit") as client:
            headers = {"Authorization": "Bearer token"}
            foreign = await client.get("/v1/events", params={"tenant": tenant_b}, headers=headers)
            own = await client.get("/v1/events", params={"tenant": tenant_a}, headers=headers)
            filtered = await client.get(
                "/v1/events", params={"tenant": tenant_a, "action": "tool.call"}, headers=headers
            )
        return foreign, own, filtered

    try:
        asyncio.run(write())
        foreign, own, filtered = asyncio.run(read())

        assert foreign.status_code == 403
        assert foreign.json() == {"error": "tenant_forbidden"}
        assert own.status_code == 200
        assert [e["event_id"] for e in own.json()["events"]] == [
            f"{tenant_a}-e1",
            f"{tenant_a}-e0",
        ]
        assert filtered.status_code == 200
        assert [e["event_id"] for e in filtered.json()["events"]] == [f"{tenant_a}-e1"]
    finally:
        _delete(tenant_a, tenant_b)


@_live
@_needs_driver
def test_console_db_roundtrip():
    from google.adk.agents import LlmAgent

    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)
    query = PostgresAuditQuery(_LIVE_URL)
    agents = {
        "probe": LlmAgent(
            name="probe", model="gemini-2.5-pro", description="probe", instruction="x"
        )
    }

    async def scenario():
        await sink.emit(_event(0, tenant=tenant))
        provider = _Provider(Principal(tenant=tenant, subject="alice", kind="human"))
        app = build_console_app(
            agents, auth_token=None, oidc=provider, audit_sink=sink, audit_query=query
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://console") as client:
            response = await client.get("/api/audit", headers={"Authorization": "Bearer token"})
        await sink.aclose()
        await query.aclose()
        return response

    try:
        response = asyncio.run(scenario())
        assert response.status_code == 200
        assert [e["event_id"] for e in response.json()] == [f"{tenant}-e0"]
    finally:
        _delete(tenant)
