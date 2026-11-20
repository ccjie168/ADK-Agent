"""RAG ingestion: chunk, embed, and upsert with ACL bound at ingestion (ADR-0035)."""

from __future__ import annotations

from typing import Protocol

from ..core import DataClass, EmbeddingRequest, EmbeddingResponse, Invocation, ModelPolicy
from .vector_store import RagChunk


class ChunkStore(Protocol):
    async def upsert(self, chunks: list[RagChunk]) -> None: ...


class Embedder(Protocol):
    async def embed(
        self, invocation: Invocation, request: EmbeddingRequest, policy: ModelPolicy
    ) -> EmbeddingResponse: ...


def split_text(text: str, *, max_chars: int) -> list[str]:
    """Split on whitespace into pieces no longer than ``max_chars``."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    pieces: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        while len(word) > max_chars:
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        current = word
    if current:
        pieces.append(current)
    return pieces


class IngestionPipeline:
    """Chunk a source, embed the chunks, and store them with their ACL."""

    def __init__(
        self,
        store: ChunkStore,
        embedder: Embedder,
        *,
        provider: str,
        model: str,
        chunk_chars: int = 800,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.provider = provider
        self.model = model
        self.chunk_chars = chunk_chars

    async def ingest(
        self,
        invocation: Invocation,
        *,
        tenant: str,
        source_id: str,
        text: str,
        data_classes: list[DataClass],
        policy: ModelPolicy,
        allowed_subjects: list[str] | None = None,
    ) -> int:
        pieces = split_text(text, max_chars=self.chunk_chars)
        if not pieces:
            raise ValueError("text has no content to ingest")
        response = await self.embedder.embed(
            invocation,
            EmbeddingRequest(provider=self.provider, model=self.model, texts=pieces),
            policy,
        )
        if len(response.vectors) != len(pieces):
            raise ValueError(
                f"embedder returned {len(response.vectors)} vectors for {len(pieces)} chunks"
            )
        chunks = [
            RagChunk(
                tenant=tenant,
                source_id=source_id,
                chunk_id=f"c{index}",
                text=piece,
                embedding=list(vector),
                data_classes=data_classes,
                allowed_subjects=allowed_subjects,
            )
            for index, (piece, vector) in enumerate(zip(pieces, response.vectors, strict=True))
        ]
        await self.store.upsert(chunks)
        return len(chunks)


__all__ = ["ChunkStore", "Embedder", "IngestionPipeline", "split_text"]
