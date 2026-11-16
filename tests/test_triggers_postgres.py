"""SLICE-124: the Postgres trigger store (live case needs TEST_POSTGRES_URL)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone

import pytest

from adk_agent.core import AgentTrigger, TriggerNotFound
from adk_agent.registry import PostgresTriggerStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")

_DIGEST = "sha256:" + "b" * 64


def _trigger(tenant: str, trigger_id: str) -> AgentTrigger:
    return AgentTrigger(
        trigger_id=trigger_id,
        tenant=tenant,
        agent_id="assistant",
        version="1.0.0",
        digest=_DIGEST,
        kind="schedule",
        every_seconds=3600,
        input="Summarize yesterday.",
        created_by="admin",
        created_at=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    )


@_live
@_needs_driver
def test_postgres_roundtrip_and_isolation():
    store = PostgresTriggerStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    other = f"other{suffix}"
    trigger_id = f"trig{suffix}"
    acme = _trigger(tenant, trigger_id)
    foreign = _trigger(other, trigger_id)

    async def flow() -> None:
        try:
            assert await store.add(acme) == acme
            assert await store.add(acme) == acme
            assert await store.get(tenant, trigger_id) == acme
            assert await store.get(other, trigger_id) is None

            assert await store.add(foreign) == foreign
            listed = await store.list(tenant)
            assert [trigger.tenant for trigger in listed] == [tenant]

            every = await store.list_all()
            keys = {(trigger.tenant, trigger.trigger_id) for trigger in every}
            assert {(tenant, trigger_id), (other, trigger_id)} <= keys

            disabled = await store.disable(tenant, trigger_id, by="alice")
            again = await store.disable(tenant, trigger_id, by="bob")
            assert disabled.enabled is False
            assert again.enabled is False
            assert (await store.get(tenant, trigger_id)).enabled is False

            with pytest.raises(TriggerNotFound):
                await store.disable(tenant, "missing", by="alice")
        finally:
            await store.aclose()

    asyncio.run(flow())
