"""SLICE-189: pgvector chunk store with ACL filters (ADR-0035 slice 1)."""

from __future__ import annotations

import asyncio
import importlib.util
import os

import pytest
from pydantic import ValidationError

from adk_agent.rag.vector_store import PgVectorRagStore, RagChunk, RagStoreUnavailable

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _chunk(**overrides) -> RagChunk:
    data = {
        "tenant": "acme",
        "source_id": "doc-1",
        "chunk_id": "c1",
        "text": "purchase order 123",
        "embedding": [0.1, 0.2, 0.3],
        "data_classes": ["internal"],
    }
    data.update(overrides)
    return RagChunk(**data)


def test_rag_chunk_validates_embedding_dimensions():
    store = PgVectorRagStore(_LIVE_URL or "postgresql://user@127.0.0.1:5432/adk", dimensions=3)
    store.validate(_chunk())
    with pytest.raises(RagStoreUnavailable):
        store.validate(_chunk(embedding=[0.1, 0.2]))
    with pytest.raises(ValidationError):
        _chunk(embedding=[])


@_live
@_needs_driver
def test_upsert_and_search_roundtrip():
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    store = PgVectorRagStore(_LIVE_URL, dimensions=3)

    async def flow() -> None:
        try:
            await store.upsert(
                [
                    _chunk(
                        tenant=tenant,
                        chunk_id="near",
                        text="purchase order 123",
                        embedding=[1.0, 0.0, 0.0],
                    ),
                    _chunk(
                        tenant=tenant,
                        chunk_id="far",
                        text="unrelated invoice",
                        embedding=[0.0, 1.0, 0.0],
                    ),
                ]
            )
            rows = await store.search(tenant, [1.0, 0.0, 0.0], data_classes=["internal"])
            assert [row.chunk_id for row in rows] == ["near", "far"]
        finally:
            await store.aclose()

    asyncio.run(flow())


@_live
@_needs_driver
def test_search_filters_by_data_classes():
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    store = PgVectorRagStore(_LIVE_URL, dimensions=3)

    async def flow() -> None:
        try:
            await store.upsert(
                [
                    _chunk(tenant=tenant, chunk_id="public", data_classes=["public"]),
                    _chunk(tenant=tenant, chunk_id="secret", data_classes=["confidential"]),
                ]
            )
            rows = await store.search(tenant, [0.1, 0.2, 0.3], data_classes=["public"])
            assert [row.chunk_id for row in rows] == ["public"]
        finally:
            await store.aclose()

    asyncio.run(flow())


@_live
@_needs_driver
def test_search_filters_by_subject():
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    store = PgVectorRagStore(_LIVE_URL, dimensions=3)

    async def flow() -> None:
        try:
            await store.upsert(
                [
                    _chunk(tenant=tenant, chunk_id="mine", allowed_subjects=["alice"]),
                    _chunk(tenant=tenant, chunk_id="theirs", allowed_subjects=["bob"]),
                ]
            )
            rows = await store.search(
                tenant, [0.1, 0.2, 0.3], data_classes=["internal"], subject="alice"
            )
            assert [row.chunk_id for row in rows] == ["mine"]
        finally:
            await store.aclose()

    asyncio.run(flow())


@_live
@_needs_driver
def test_search_is_tenant_scoped():
    suffix = os.urandom(4).hex()
    tenant_a = f"acmea{suffix}"
    tenant_b = f"acmeb{suffix}"
    store = PgVectorRagStore(_LIVE_URL, dimensions=3)

    async def flow() -> None:
        try:
            await store.upsert([_chunk(tenant=tenant_a, chunk_id="a1")])
            rows = await store.search(tenant_b, [0.1, 0.2, 0.3], data_classes=["internal"])
            assert rows == []
        finally:
            await store.aclose()

    asyncio.run(flow())
