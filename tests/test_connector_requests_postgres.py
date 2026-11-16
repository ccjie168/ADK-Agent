"""SLICE-122: the Postgres connector request store (live case needs TEST_POSTGRES_URL)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone

import pytest

from adk_agent.core import ConnectorRequest, ConnectorRequestConflict, ConnectorSpec
from adk_agent.registry import PostgresConnectorRequestStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _request(request_id: str, tenant: str, **overrides) -> ConnectorRequest:
    data = {
        "request_id": request_id,
        "tenant": tenant,
        "spec": ConnectorSpec(
            connector_id=f"crm{tenant}",
            tenant=tenant,
            kind="http",
            base_url="https://crm.example.com",
            auth_ref=f"secret://{tenant}/token",
            methods=["GET"],
            path_prefixes=["/v1/crm/"],
            data_classes=["internal"],
        ),
        "reason": "Need CRM read access",
        "requested_by": "alice",
        "requested_at": datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return ConnectorRequest(**data)


@_live
@_needs_driver
def test_postgres_roundtrip():
    store = PostgresConnectorRequestStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    record = _request(f"req{suffix}", f"acme{suffix}")

    async def flow() -> None:
        try:
            assert await store.add(record) == record
            assert await store.add(record) == record
            assert await store.get(record.request_id) == record
            assert await store.get(f"missing{suffix}") is None
            listed = await store.list(record.tenant)
            assert [item.request_id for item in listed] == [record.request_id]
        finally:
            await store.aclose()

    asyncio.run(flow())


@_live
@_needs_driver
def test_postgres_decide_is_single_winner():
    store = PostgresConnectorRequestStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    record = _request(f"req{suffix}", f"acme{suffix}")

    async def flow() -> None:
        try:
            await store.add(record)
            results = await asyncio.gather(
                store.decide(
                    record.request_id,
                    approved=True,
                    decided_by="admin",
                    reason="ok",
                    registered_connector=record.spec.connector_id,
                ),
                store.decide(
                    record.request_id,
                    approved=False,
                    decided_by="admin",
                    reason="no",
                ),
                return_exceptions=True,
            )
            winners = [item for item in results if not isinstance(item, Exception)]
            conflicts = [item for item in results if isinstance(item, ConnectorRequestConflict)]
            assert len(winners) == 1
            assert len(conflicts) == 1
        finally:
            await store.aclose()

    asyncio.run(flow())
