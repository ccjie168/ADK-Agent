"""SLICE-111: checkpoints are shared through Postgres.

Set TEST_POSTGRES_URL to run the live case against a real database.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest

from adk_agent.orchestration import PostgresCheckpointStore, RunCheckpoint

_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")


@_live
def test_roundtrip_and_tenant_scope() -> None:
    assert _LIVE_URL is not None
    store = PostgresCheckpointStore(_LIVE_URL)
    tenant = f"slice111-{uuid.uuid4().hex}"
    checkpoint = RunCheckpoint(
        tenant=tenant,
        run_id="run-1",
        plan_id="flow",
        plan_version="1.0.0",
        plan_digest="d" * 64,
        status="waiting_approval",
        outputs={"a": "out:one"},
        spent_usd=0.5,
        completed_steps=["a"],
        waiting_step="b",
        final_text="",
        updated_at=datetime.now(timezone.utc),
    )

    async def scenario() -> None:
        await store.save(checkpoint)
        loaded = await store.load(tenant, checkpoint.run_id)
        assert loaded is not None
        assert loaded.status == "waiting_approval"
        assert loaded.outputs == {"a": "out:one"}
        assert loaded.completed_steps == ["a"]
        assert loaded.waiting_step == "b"
        assert await store.load("other-tenant", checkpoint.run_id) is None
        await store.close()

    asyncio.run(scenario())


@_live
def test_approval_request_id_roundtrip() -> None:
    """SLICE-310: the deferred request id survives a Postgres roundtrip."""
    assert _LIVE_URL is not None
    store = PostgresCheckpointStore(_LIVE_URL)
    tenant = f"slice310-{uuid.uuid4().hex}"
    checkpoint = RunCheckpoint(
        tenant=tenant,
        run_id="run-deferred",
        plan_id="flow",
        plan_version="1.0.0",
        plan_digest="e" * 64,
        status="waiting_approval",
        completed_steps=["a"],
        waiting_step="b",
        approval_request_id="request-1",
        updated_at=datetime.now(timezone.utc),
    )

    async def scenario() -> None:
        await store.save(checkpoint)
        loaded = await store.load(tenant, checkpoint.run_id)
        assert loaded is not None
        assert loaded.approval_request_id == "request-1"
        await store.close()

    asyncio.run(scenario())
