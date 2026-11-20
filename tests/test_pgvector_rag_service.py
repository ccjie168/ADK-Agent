"""SLICE-192: PgVectorRagService retrieval over the vector store (ADR-0035 slice 4)."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import (
    AgentRef,
    EmbeddingRequest,
    EmbeddingResponse,
    Invocation,
    ModelPolicy,
    Principal,
)
from adk_agent.rag import PgVectorRagService, RagGuard
from adk_agent.rag.vector_store import RagChunkRow


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="q",
    )


POLICY = ModelPolicy(provider_allowlist=["fake"])


class FakeEmbedder:
    def __init__(self) -> None:
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, invocation, request, policy) -> EmbeddingResponse:
        self.requests.append(request)
        return EmbeddingResponse(
            vectors=[[0.5, 0.5, 0.5]],
            model=request.model,
            input_tokens=1,
            egress="third_party",
        )


class FakeStore:
    def __init__(self, rows: list[RagChunkRow]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    async def search(
        self, tenant, embedding, *, data_classes, subject=None, limit=10
    ) -> list[RagChunkRow]:
        self.calls.append(
            {
                "tenant": tenant,
                "embedding": embedding,
                "data_classes": data_classes,
                "subject": subject,
                "limit": limit,
            }
        )
        return self.rows


def _row(chunk_id: str, distance: float) -> RagChunkRow:
    return RagChunkRow(
        source_id="doc",
        chunk_id=chunk_id,
        text=f"text {chunk_id}",
        data_classes=["internal"],
        distance=distance,
    )


def _service(rows, guard=None) -> tuple[PgVectorRagService, FakeEmbedder, FakeStore]:
    embedder = FakeEmbedder()
    store = FakeStore(rows)
    service = PgVectorRagService(store, embedder, provider="fake", model="embed-model", guard=guard)
    return service, embedder, store


def _retrieve(service) -> list:
    principal = Principal(tenant="acme", subject="alice", kind="human")
    return asyncio.run(
        service.retrieve(
            "what is the order",
            principal,
            ["internal"],
            invocation=_invocation(),
            policy=POLICY,
        )
    )


def test_retrieve_embeds_and_searches():
    service, embedder, store = _service([_row("c1", distance=0.0)])
    results = _retrieve(service)
    assert [citation.source_id for citation in results] == ["doc"]
    assert results[0].acl_checked is True
    assert embedder.requests[0].texts == ["what is the order"]
    assert store.calls[0]["tenant"] == "acme"
    assert store.calls[0]["subject"] == "alice"
    assert store.calls[0]["data_classes"] == ["internal"]
    assert store.calls[0]["embedding"] == [0.5, 0.5, 0.5]


def test_retrieve_maps_distance_to_confidence():
    service, _, _ = _service([_row("near", 0.0), _row("halfway", 1.0), _row("far", 2.0)])
    results = _retrieve(service)
    assert [round(citation.confidence, 3) for citation in results] == [1.0, 0.5, 0.0]


def test_retrieve_applies_guard():
    service, _, _ = _service([_row("near", 0.0), _row("far", 2.0)], guard=RagGuard())
    results = _retrieve(service)
    assert [citation.snippet for citation in results] == ["text near"]


def test_retrieve_requires_invocation_and_policy():
    service, _, _ = _service([_row("c1", 0.0)])
    principal = Principal(tenant="acme", subject="alice", kind="human")
    with pytest.raises(ValueError):
        asyncio.run(service.retrieve("q", principal, ["internal"]))


def test_retrieve_empty():
    service, _, _ = _service([])
    assert _retrieve(service) == []
