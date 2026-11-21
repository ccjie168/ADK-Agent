"""SLICE-211: replacing a source drops its stale chunks (live case needs TEST_POSTGRES_URL)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest

from adk_agent.rag.vector_store import PgVectorRagStore, RagChunk

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _chunk(tenant: str, source_id: str, chunk_id: str) -> RagChunk:
    return RagChunk(
        tenant=tenant,
        source_id=source_id,
        chunk_id=chunk_id,
        text=f"text {chunk_id}",
        embedding=[0.1, 0.2, 0.3, 0.4],
        data_classes=["internal"],
    )


@_live
@_needs_driver
def test_replace_removes_stale_chunks():
    tenant = f"slice211-{uuid.uuid4().hex[:8]}"

    async def run():
        store = PgVectorRagStore(_LIVE_URL, dimensions=4)
        try:
            await store.replace([_chunk(tenant, "doc", "c0"), _chunk(tenant, "doc", "c1")])
            await store.replace([_chunk(tenant, "doc", "c0")])
            await store.replace([_chunk(tenant, "other", "c0")])

            return await store.search(tenant, [0.1, 0.2, 0.3, 0.4], data_classes=["internal"])
        finally:
            await store.aclose()

    rows = asyncio.run(run())

    assert sorted((row.source_id, row.chunk_id) for row in rows) == [
        ("doc", "c0"),
        ("other", "c0"),
    ]
