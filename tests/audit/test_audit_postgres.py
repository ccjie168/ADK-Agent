"""SLICE-096: Postgres audit sink, query, and chain verification."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from adk_agent import cli
from adk_agent.audit import (
    AuditChainBroken,
    AuditSignatureInvalid,
    AuditStoreUnavailable,
    PostgresAuditQuery,
    PostgresAuditSink,
    SigningKeyring,
    query_audit_records,
    verify_audit_database,
)
from adk_agent.audit.pipeline import record_hash
from adk_agent.core import AgentRef, AuditEvent, Principal

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _tenant() -> str:
    return "t" + uuid.uuid4().hex[:12]


def _event(
    index: int,
    *,
    tenant: str,
    trace: str = "tr1",
    run: str = "r1",
    action: str = "model.call",
    status: str = "ok",
    at: datetime | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=f"{tenant}-e{index}",
        run_id=run,
        trace_id=trace,
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action=action,
        target="litellm:deepseek",
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


def _chain_links(rows) -> bool:
    prev = ""
    for row in rows:
        if row["prev_hash"] != prev:
            return False
        event = AuditEvent.model_validate_json(row["event"])
        if record_hash(event, row["prev_hash"]) != row["hash"]:
            return False
        prev = row["hash"]
    return True


def _mutate_event(tenant: str, sequence: int) -> None:
    async def scenario():
        conn = await _connect()
        try:
            await conn.execute(
                "UPDATE adk_audit_records SET event = event || $1::jsonb "
                "WHERE tenant = $2 AND sequence = $3",
                json.dumps({"target": "tampered"}),
                tenant,
                sequence,
            )
        finally:
            await conn.close()

    asyncio.run(scenario())


def _null_signature(tenant: str, sequence: int) -> None:
    async def scenario():
        conn = await _connect()
        try:
            await conn.execute(
                "UPDATE adk_audit_records SET signature = NULL WHERE tenant = $1 AND sequence = $2",
                tenant,
                sequence,
            )
        finally:
            await conn.close()

    asyncio.run(scenario())


def test_sink_rejects_both_keys():
    keyring = SigningKeyring(active="k1", keys={"k1": "secret"})
    with pytest.raises(ValueError):
        PostgresAuditSink("postgresql://x/x", signing_key="k1", keyring=keyring)


def test_unsupported_url_rejected():
    with pytest.raises(AuditStoreUnavailable):
        PostgresAuditSink("mysql://localhost/adk")


def test_query_validation():
    with pytest.raises(ValueError):
        asyncio.run(query_audit_records("postgresql://x/x", limit=0))
    with pytest.raises(ValueError):
        asyncio.run(query_audit_records("postgresql://x/x", order="sideways"))


def test_cli_verify_exclusive(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit"])
    assert exc.value.code == 2
    assert "exactly one" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit", "audit.jsonl", "--audit-db", "postgresql://x/x"])
    assert exc.value.code == 2


@_live
@_needs_driver
def test_per_tenant_chains():
    a = _tenant()
    b = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)

    async def scenario():
        for i in range(3):
            await sink.emit(_event(i, tenant=a))
        for i in range(2):
            await sink.emit(_event(i, tenant=b))
        await sink.aclose()

    try:
        asyncio.run(scenario())

        rows_a = _rows(a)
        rows_b = _rows(b)
        assert [r["sequence"] for r in rows_a] == [1, 2, 3]
        assert [r["sequence"] for r in rows_b] == [1, 2]
        assert _chain_links(rows_a)
        assert _chain_links(rows_b)
        assert asyncio.run(verify_audit_database(_LIVE_URL)) >= 5
    finally:
        _delete(a, b)


@_live
@_needs_driver
def test_concurrent_writes():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)
    events = [_event(i, tenant=tenant) for i in range(30)]

    async def scenario():
        await asyncio.gather(*(sink.emit(event) for event in events))
        await sink.aclose()

    try:
        asyncio.run(scenario())

        rows = _rows(tenant)
        assert [r["sequence"] for r in rows] == list(range(1, 31))
        assert _chain_links(rows)
        assert asyncio.run(verify_audit_database(_LIVE_URL)) >= 30
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_query_filters():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)

    async def scenario():
        await sink.emit(_event(0, tenant=tenant))
        await sink.emit(_event(1, tenant=tenant, trace="tr2"))
        await sink.emit(_event(2, tenant=tenant, run="r2"))
        await sink.emit(_event(3, tenant=tenant, action="tool.call"))
        await sink.emit(_event(4, tenant=tenant, status="denied"))
        await sink.aclose()

    def q(**kwargs):
        return asyncio.run(query_audit_records(_LIVE_URL, tenant=tenant, **kwargs))

    try:
        asyncio.run(scenario())

        ids = [f"{tenant}-e{i}" for i in range(5)]
        assert [e.event_id for e in q()] == list(reversed(ids))
        assert [e.event_id for e in q(order="asc")] == ids
        assert [e.event_id for e in q(trace_id="tr2")] == [f"{tenant}-e1"]
        assert [e.event_id for e in q(run_id="r2")] == [f"{tenant}-e2"]
        assert [e.event_id for e in q(action="tool.call")] == [f"{tenant}-e3"]
        assert [e.event_id for e in q(status="denied")] == [f"{tenant}-e4"]
        assert [e.event_id for e in q(limit=2)] == [f"{tenant}-e4", f"{tenant}-e3"]
        since = START + timedelta(seconds=1)
        until = START + timedelta(seconds=3)
        assert [e.event_id for e in q(since=since, until=until, order="asc")] == [
            f"{tenant}-e1",
            f"{tenant}-e2",
            f"{tenant}-e3",
        ]
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_postgres_audit_query():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)
    query = PostgresAuditQuery(_LIVE_URL)

    async def scenario():
        for i in range(3):
            await sink.emit(_event(i, tenant=tenant))
        await sink.aclose()

    async def read():
        events = await query.events(tenant=tenant, limit=2)
        await query.aclose()
        return events

    try:
        asyncio.run(scenario())
        events = asyncio.run(read())
        assert [e.event_id for e in events] == [f"{tenant}-e2", f"{tenant}-e1"]
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_tamper_detected():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)

    async def scenario():
        for i in range(3):
            await sink.emit(_event(i, tenant=tenant))
        await sink.aclose()

    try:
        asyncio.run(scenario())
        _mutate_event(tenant, 2)
        with pytest.raises(AuditChainBroken) as exc:
            asyncio.run(verify_audit_database(_LIVE_URL))
        assert exc.value.tenant == tenant
        assert exc.value.index == 2
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_signatures():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL, signing_key="k1")

    async def scenario():
        for i in range(2):
            await sink.emit(_event(i, tenant=tenant))
        await sink.aclose()

    try:
        asyncio.run(scenario())

        rows = _rows(tenant)
        assert all(r["signature"] is not None and r["kid"] is None for r in rows)
        assert asyncio.run(verify_audit_database(_LIVE_URL, signing_key="k1")) >= 2

        _null_signature(tenant, 2)
        with pytest.raises(AuditSignatureInvalid) as exc:
            asyncio.run(verify_audit_database(_LIVE_URL, signing_key="k1"))
        assert exc.value.tenant == tenant
        assert exc.value.index == 2
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_keyring_signatures():
    tenant = _tenant()
    keyring = SigningKeyring(active="k1", keys={"k1": "secret-one"})
    sink = PostgresAuditSink(_LIVE_URL, keyring=keyring)

    async def scenario():
        await sink.emit(_event(0, tenant=tenant))
        await sink.aclose()

    try:
        asyncio.run(scenario())

        rows = _rows(tenant)
        assert rows[0]["kid"] == "k1"
        assert asyncio.run(verify_audit_database(_LIVE_URL, keyring=keyring)) >= 1
    finally:
        _delete(tenant)


@_live
@_needs_driver
def test_cli_verify_database(monkeypatch, capsys):
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL, signing_key="k1")

    async def scenario():
        for i in range(2):
            await sink.emit(_event(i, tenant=tenant))
        await sink.aclose()

    monkeypatch.setenv("ADK_AUDIT_SIGNING_KEY", "k1")
    monkeypatch.delenv("ADK_AUDIT_KEYRING", raising=False)
    try:
        asyncio.run(scenario())
        cli.main(["verify-audit", "--audit-db", _LIVE_URL])
    finally:
        _delete(tenant)

    out = capsys.readouterr().out
    assert re.search(r"^ok \d+ records$", out.strip())


def _corrupt_event(tenant: str, sequence: int) -> None:
    async def scenario():
        conn = await _connect()
        try:
            await conn.execute(
                "UPDATE adk_audit_records SET event = $1::jsonb "
                "WHERE tenant = $2 AND sequence = $3",
                json.dumps({"broken": True}),
                tenant,
                sequence,
            )
        finally:
            await conn.close()

    asyncio.run(scenario())


@_live
def test_corrupt_event_detected_as_chain_break():
    tenant = _tenant()
    sink = PostgresAuditSink(_LIVE_URL)

    async def scenario():
        await sink.emit(_event(0, tenant=tenant))
        await sink.aclose()

    try:
        asyncio.run(scenario())
        _corrupt_event(tenant, 1)
        with pytest.raises(AuditChainBroken) as exc:
            asyncio.run(verify_audit_database(_LIVE_URL))
        assert exc.value.tenant == tenant
        assert exc.value.index == 1
    finally:
        _delete(tenant)
