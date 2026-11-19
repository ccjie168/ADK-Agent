"""SLICE-173: tool idempotency store (file + Postgres), single-winner claim."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import ToolExecutionRecord, ToolIdempotencyConflict
from adk_agent.tools import FileToolIdempotencyStore

_NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _record(**overrides) -> ToolExecutionRecord:
    data = {
        "tenant": "acme",
        "tool_id": "write.po",
        "idempotency_key": "key-1",
        "status": "claimed",
        "created_at": _NOW,
        "expires_at": _NOW + timedelta(hours=24),
    }
    data.update(overrides)
    return ToolExecutionRecord(**data)


def test_claim_has_a_single_winner(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    first = asyncio.run(store.claim(_record()))
    second = asyncio.run(store.claim(_record()))
    assert first.idempotency_key == "key-1"
    assert second == first


def test_claim_returns_existing(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    claimed = asyncio.run(store.claim(_record()))
    again = asyncio.run(store.claim(_record(status="completed", finished_at=_NOW)))
    assert again == claimed
    assert again.status == "claimed"


def test_finish_updates_the_record(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    asyncio.run(store.claim(_record()))
    finished = asyncio.run(
        store.finish(
            "acme",
            "write.po",
            "key-1",
            status="completed",
            output=42,
            data_classes=("internal",),
        )
    )
    assert finished.status == "completed"
    assert finished.output == 42
    assert finished.finished_at is not None


def test_finish_unknown_key_is_a_conflict(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    with pytest.raises(ToolIdempotencyConflict):
        asyncio.run(store.finish("acme", "write.po", "missing", status="completed"))


def test_record_terminal_state_constraints():
    with pytest.raises(ValidationError):
        _record(status="completed")
    with pytest.raises(ValidationError):
        _record(status="claimed", finished_at=_NOW)
    with pytest.raises(ValidationError):
        _record(expires_at=_NOW - timedelta(seconds=1))
    assert _record(status="completed", finished_at=_NOW).status == "completed"


def test_file_store_unsafe_paths_are_rejected(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(store.get("../escape", "write.po", "key-1"))
    with pytest.raises(ValueError):
        asyncio.run(store.get("acme", "../escape", "key-1"))


@_live
@_needs_driver
def test_postgres_claim_has_a_single_winner():
    from adk_agent.tools import PostgresToolIdempotencyStore

    store = PostgresToolIdempotencyStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    tool_id = f"write{suffix}"
    key = f"key-{suffix}"

    async def flow() -> None:
        try:
            first = await store.claim(_record(tenant=tenant, tool_id=tool_id, idempotency_key=key))
            assert first.idempotency_key == key
            assert (
                await store.claim(_record(tenant=tenant, tool_id=tool_id, idempotency_key=key))
                == first
            )
            assert await store.get(tenant, tool_id, key) == first
        finally:
            await store.aclose()

    asyncio.run(flow())
