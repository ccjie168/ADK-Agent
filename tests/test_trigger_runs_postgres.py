"""SLICE-125: the Postgres trigger fire store (live case needs TEST_POSTGRES_URL)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone

import pytest

from adk_agent.core import TriggerFire, TriggerFireConflict
from adk_agent.registry import PostgresTriggerFireStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _fire(tenant: str, trigger_id: str, key: str, run_id: str) -> TriggerFire:
    return TriggerFire(
        tenant=tenant,
        trigger_id=trigger_id,
        idempotency_key=key,
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        status="running",
        created_at=datetime.now(timezone.utc),
    )


@_live
@_needs_driver
def test_postgres_roundtrip_and_claim_race():
    store = PostgresTriggerFireStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    trigger_id = f"trig{suffix}"
    key = f"key-{suffix}"
    race_key = f"race-{suffix}"

    async def flow() -> None:
        try:
            first = await store.claim(_fire(tenant, trigger_id, key, "run-1"))
            assert first.run_id == "run-1"
            assert await store.claim(_fire(tenant, trigger_id, key, "run-2")) == first
            assert await store.get(tenant, trigger_id, key) == first

            raced = await asyncio.gather(
                store.claim(_fire(tenant, trigger_id, race_key, "a")),
                store.claim(_fire(tenant, trigger_id, race_key, "b")),
            )
            assert len({record.run_id for record in raced}) == 1

            finished = await store.finish(tenant, trigger_id, key, status="ok")
            assert finished.status == "ok"
            assert finished.finished_at is not None
            assert await store.get(tenant, trigger_id, key) == finished

            with pytest.raises(TriggerFireConflict):
                await store.finish(tenant, trigger_id, "missing-key", status="ok")
        finally:
            await store.aclose()

    asyncio.run(flow())
