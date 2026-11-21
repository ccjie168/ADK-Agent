"""Postgres + pgvector chunk store with tenant RLS (ADR-0035)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from ..core import DataClass
from ..pg import LazyPool

_Subject = Annotated[str, Field(min_length=1)]


class RagStoreUnavailable(Exception):
    """The vector store cannot serve the request (missing extension, bad dimensions)."""


class RagChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
    data_classes: list[DataClass] = Field(default_factory=list)
    allowed_subjects: list[_Subject] | None = None


class RagChunkRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    chunk_id: str
    text: str
    data_classes: list[DataClass]
    distance: float = 0.0


_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS adk_rag_chunks (
    tenant text,
    source_id text,
    chunk_id text,
    body text NOT NULL,
    embedding vector({dimensions}),
    data_classes text[] NOT NULL DEFAULT '{{}}',
    allowed_subjects text[],
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, source_id, chunk_id)
);
ALTER TABLE adk_rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE adk_rag_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS adk_rag_chunks_tenant ON adk_rag_chunks;
CREATE POLICY adk_rag_chunks_tenant ON adk_rag_chunks
    USING (tenant = current_setting('app.tenant_id', true));
"""


class PgVectorRagStore:
    """Chunks live in ``adk_rag_chunks``; every query runs under the tenant setting."""

    def __init__(self, url: str, *, dimensions: int) -> None:
        if dimensions <= 0:
            raise RagStoreUnavailable("dimensions must be positive")
        self.dimensions = dimensions
        self._dsn = url
        self._pool = LazyPool(
            url,
            what="rag vector store",
            unavailable=RagStoreUnavailable,
            setup=self._ensure_schema,
        )

    def validate(self, chunk: RagChunk) -> None:
        if len(chunk.embedding) != self.dimensions:
            raise RagStoreUnavailable(
                f"embedding has {len(chunk.embedding)} dimensions, expected {self.dimensions}"
            )

    async def _ensure_schema(self, pool: Any) -> None:
        async with pool.acquire() as conn:
            await conn.execute(_SCHEMA.format(dimensions=self.dimensions))

    async def upsert(self, chunks: list[RagChunk]) -> None:
        for chunk in chunks:
            self.validate(chunk)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    chunks[0].tenant if chunks else "",
                )
                await self._write(conn, chunks)
        except RagStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RagStoreUnavailable(f"rag vector write failed ({type(exc).__name__})") from exc

    async def replace(self, chunks: list[RagChunk]) -> None:
        """Replace one source's chunk set in one transaction, dropping stale chunks."""
        for chunk in chunks:
            self.validate(chunk)
        if not chunks:
            return
        tenant, source_id = chunks[0].tenant, chunks[0].source_id
        if any(chunk.tenant != tenant or chunk.source_id != source_id for chunk in chunks):
            raise ValueError("replace takes chunks from exactly one tenant and source")
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
                await conn.execute(
                    "DELETE FROM adk_rag_chunks "
                    "WHERE tenant = $1 AND source_id = $2 AND chunk_id <> ALL($3::text[])",
                    tenant,
                    source_id,
                    [chunk.chunk_id for chunk in chunks],
                )
                await self._write(conn, chunks)
        except RagStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RagStoreUnavailable(f"rag vector write failed ({type(exc).__name__})") from exc

    async def _write(self, conn: Any, chunks: list[RagChunk]) -> None:
        for chunk in chunks:
            await conn.execute(
                "INSERT INTO adk_rag_chunks "
                "(tenant, source_id, chunk_id, body, embedding, data_classes, "
                "allowed_subjects, updated_at) "
                "VALUES ($1, $2, $3, $4, $5::vector, $6, $7, $8) "
                "ON CONFLICT (tenant, source_id, chunk_id) DO UPDATE SET "
                "body = EXCLUDED.body, embedding = EXCLUDED.embedding, "
                "data_classes = EXCLUDED.data_classes, "
                "allowed_subjects = EXCLUDED.allowed_subjects, "
                "updated_at = EXCLUDED.updated_at",
                chunk.tenant,
                chunk.source_id,
                chunk.chunk_id,
                chunk.text,
                _vector_literal(chunk.embedding),
                list(chunk.data_classes),
                chunk.allowed_subjects,
                datetime.now(timezone.utc),
            )

    async def search(
        self,
        tenant: str,
        embedding: list[float],
        *,
        data_classes: list[DataClass],
        subject: str | None = None,
        limit: int = 10,
    ) -> list[RagChunkRow]:
        if len(embedding) != self.dimensions:
            raise RagStoreUnavailable(
                f"query has {len(embedding)} dimensions, expected {self.dimensions}"
            )
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
                rows = await conn.fetch(
                    "SELECT source_id, chunk_id, body, data_classes, "
                    "embedding <=> $4::vector AS distance FROM adk_rag_chunks "
                    "WHERE tenant = $1 "
                    "AND data_classes <@ $2::text[] "
                    "AND (allowed_subjects IS NULL OR $3::text = ANY(allowed_subjects)) "
                    "ORDER BY embedding <=> $4::vector "
                    "LIMIT $5",
                    tenant,
                    list(data_classes),
                    subject or "",
                    _vector_literal(embedding),
                    limit,
                )
        except RagStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RagStoreUnavailable(f"rag vector search failed ({type(exc).__name__})") from exc
        return [
            RagChunkRow(
                source_id=row["source_id"],
                chunk_id=row["chunk_id"],
                text=row["body"],
                data_classes=list(row["data_classes"]),
                distance=float(row["distance"]),
            )
            for row in rows
        ]

    async def aclose(self) -> None:
        await self._pool.close()


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


__all__ = ["PgVectorRagStore", "RagChunk", "RagChunkRow", "RagStoreUnavailable"]
