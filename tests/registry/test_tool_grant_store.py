"""SLICE-078: file and Postgres tool grant stores."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from adk_agent.core import ToolGrantRequest
from adk_agent.registry import (
    FileToolGrantStore,
    GrantRequestConflict,
    GrantRequestExpired,
    PostgresToolGrantStore,
)

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + "a" * 64


def _request(**overrides) -> ToolGrantRequest:
    data = {
        "request_id": "r1",
        "tenant": "acme",
        "agent_id": "bot",
        "version": "1.0.0",
        "digest": DIGEST,
        "tool_id": "crm.read",
        "data_classes": ["internal"],
        "reason": "support needs it",
        "status": "pending",
        "requested_by": "alice",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=2),
    }
    data.update(overrides)
    return ToolGrantRequest(**data)


def _file(tmp_path) -> FileToolGrantStore:
    return FileToolGrantStore(tmp_path)


def test_file_add_idempotent(tmp_path):
    store = _file(tmp_path)

    assert asyncio.run(store.add(_request())) == _request()
    assert asyncio.run(store.add(_request())) == _request()
    assert asyncio.run(store.get("r1")) == _request()

    with pytest.raises(GrantRequestConflict):
        asyncio.run(store.add(_request(reason="other")))


def test_file_decide(tmp_path):
    store = _file(tmp_path)
    asyncio.run(store.add(_request()))

    approved = asyncio.run(
        store.decide("r1", approved=True, decided_by="bob", reason="ok", now=NOW)
    )

    assert approved.status == "approved"
    assert approved.decided_by == "bob"
    assert asyncio.run(store.get("r1")) == approved

    with pytest.raises(GrantRequestConflict):
        asyncio.run(store.decide("r1", approved=False, decided_by="bob", reason="no", now=NOW))


def test_file_expired_decide(tmp_path):
    store = _file(tmp_path)
    asyncio.run(store.add(_request()))

    with pytest.raises(GrantRequestExpired):
        asyncio.run(
            store.decide(
                "r1",
                approved=True,
                decided_by="bob",
                reason="late",
                now=NOW + timedelta(hours=3),
            )
        )


def test_file_cancel(tmp_path):
    store = _file(tmp_path)
    asyncio.run(store.add(_request()))

    cancelled = asyncio.run(store.cancel("r1", by="alice", reason="no longer needed", now=NOW))

    assert cancelled.status == "cancelled"
    with pytest.raises(GrantRequestConflict):
        asyncio.run(store.decide("r1", approved=True, decided_by="bob", reason="ok", now=NOW))


def test_file_active(tmp_path):
    store = _file(tmp_path)
    asyncio.run(store.add(_request()))
    assert asyncio.run(store.active("acme", "bot", "1.0.0", DIGEST, "crm.read", now=NOW)) is False

    asyncio.run(store.decide("r1", approved=True, decided_by="bob", reason="ok", now=NOW))

    assert asyncio.run(store.active("acme", "bot", "1.0.0", DIGEST, "crm.read", now=NOW)) is True
    assert (
        asyncio.run(store.active("acme", "bot", "1.0.0", "sha256:" + "b" * 64, "crm.read", now=NOW))
        is False
    )
    assert (
        asyncio.run(
            store.active("acme", "bot", "1.0.0", DIGEST, "crm.read", now=NOW + timedelta(hours=3))
        )
        is False
    )


@_live
@_needs_driver
def test_postgres_lifecycle():
    store = PostgresToolGrantStore(_LIVE_URL)
    tenant = "t" + uuid.uuid4().hex[:12]
    request = _request(request_id="r" + uuid.uuid4().hex[:12], tenant=tenant)

    assert asyncio.run(store.add(request)) == request
    assert asyncio.run(store.add(request)) == request
    assert asyncio.run(store.get(request.request_id)) == request

    approved = asyncio.run(
        store.decide(request.request_id, approved=True, decided_by="bob", reason="ok", now=NOW)
    )
    assert approved.status == "approved"
    assert asyncio.run(store.active(tenant, "bot", "1.0.0", DIGEST, "crm.read", now=NOW)) is True
    assert (
        asyncio.run(
            store.active(tenant, "bot", "1.0.0", DIGEST, "crm.read", now=NOW + timedelta(hours=3))
        )
        is False
    )
    with pytest.raises(GrantRequestConflict):
        asyncio.run(
            store.decide(request.request_id, approved=False, decided_by="bob", reason="no", now=NOW)
        )
