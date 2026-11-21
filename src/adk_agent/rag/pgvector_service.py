"""RagService over the pgvector store: embed, ACL-filter, guard (ADR-0035)."""

from __future__ import annotations

from typing import Protocol

from ..core import DataClass, EmbeddingRequest, Invocation, ModelPolicy, Principal
from .guard import RagGuard
from .ingest import Embedder
from .service import Citation
from .vector_store import RagChunkRow


class _SearchStore(Protocol):
    """Structural type for the part of the vector store retrieval needs."""

    async def search(
        self,
        tenant: str,
        embedding: list[float],
        *,
        data_classes: list[DataClass],
        subject: str | None = None,
        limit: int = 10,
    ) -> list[RagChunkRow]: ...


def _confidence(distance: float) -> float:
    """Clamp cosine similarity (1 - distance) into [0, 1] as confidence."""
    return min(1.0, max(0.0, 1.0 - distance))


class PgVectorRagService:
    """The ADR-0032 RagService backed by the pgvector chunk store."""

    def __init__(
        self,
        store: _SearchStore,
        embedder: Embedder,
        *,
        provider: str,
        model: str,
        guard: RagGuard | None = None,
        limit: int = 10,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.provider = provider
        self.model = model
        self.guard = guard
        self.limit = limit

    async def retrieve(
        self,
        query: str,
        principal: Principal,
        data_classes: list[DataClass],
        *,
        invocation: Invocation | None = None,
        policy: ModelPolicy | None = None,
    ) -> list[Citation]:
        """Embed the query, search under the caller's ACL, and cite the hits.

        ``invocation`` and ``policy`` are required: the embedding call is audited and
        budgeted like any other model call.
        """
        if invocation is None or policy is None:
            raise ValueError("retrieve needs the invocation and model policy to embed the query")
        response = await self.embedder.embed(
            invocation,
            EmbeddingRequest(provider=self.provider, model=self.model, texts=[query]),
            policy,
        )
        rows = await self.store.search(
            principal.tenant,
            list(response.vectors[0]),
            data_classes=data_classes,
            subject=principal.subject,
            limit=self.limit,
        )
        citations = [
            Citation(
                source_id=row.source_id,
                snippet=row.text,
                acl_checked=True,
                confidence=_confidence(row.distance),
            )
            for row in rows
        ]
        if self.guard is not None:
            return self.guard.filter(citations)
        return citations


__all__ = ["PgVectorRagService"]
