"""SLICE-191: RAG ingestion pipeline (ADR-0035 slice 3)."""

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
from adk_agent.rag.ingest import IngestionPipeline, split_text
from adk_agent.rag.vector_store import RagChunk


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


PUBLIC_POLICY = ModelPolicy(provider_allowlist=["fake"], model_aliases=[])


class FakeEmbedder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, invocation, request, policy) -> EmbeddingResponse:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("embedding down")
        return EmbeddingResponse(
            vectors=[[0.1, 0.2] for _ in request.texts],
            model=request.model,
            input_tokens=len(request.texts),
            egress="third_party",
        )


class FakeStore:
    def __init__(self) -> None:
        self.chunks: list[RagChunk] = []

    async def upsert(self, chunks: list[RagChunk]) -> None:
        self.chunks.extend(chunks)


def test_split_text_respects_max_chars():
    text = "alpha beta gamma\ndelta epsilon\nzeta"
    pieces = split_text(text, max_chars=12)
    assert pieces
    assert all(len(piece) <= 12 for piece in pieces)
    assert " ".join(" ".join(pieces).split()) == " ".join(text.split())


def test_ingest_writes_chunks_with_acl():
    store = FakeStore()
    embedder = FakeEmbedder()
    pipeline = IngestionPipeline(store, embedder, provider="fake", model="embed-model")
    count = asyncio.run(
        pipeline.ingest(
            _invocation(),
            tenant="acme",
            source_id="doc-1",
            text="alpha beta gamma delta",
            data_classes=["internal"],
            allowed_subjects=["alice"],
            policy=PUBLIC_POLICY,
        )
    )
    assert count == len(store.chunks) >= 1
    chunk = store.chunks[0]
    assert chunk.tenant == "acme"
    assert chunk.source_id == "doc-1"
    assert chunk.data_classes == ["internal"]
    assert chunk.allowed_subjects == ["alice"]
    assert chunk.embedding == [0.1, 0.2]
    assert len(embedder.requests) == 1


def test_ingest_rejects_empty_text():
    pipeline = IngestionPipeline(FakeStore(), FakeEmbedder(), provider="fake", model="m")
    with pytest.raises(ValueError):
        asyncio.run(
            pipeline.ingest(
                _invocation(),
                tenant="acme",
                source_id="doc-1",
                text="   ",
                data_classes=["internal"],
                policy=PUBLIC_POLICY,
            )
        )


def test_ingest_propagates_embedding_failure():
    store = FakeStore()
    pipeline = IngestionPipeline(
        store, FakeEmbedder(fail=True), provider="fake", model="embed-model"
    )
    with pytest.raises(RuntimeError):
        asyncio.run(
            pipeline.ingest(
                _invocation(),
                tenant="acme",
                source_id="doc-1",
                text="alpha beta",
                data_classes=["internal"],
                policy=PUBLIC_POLICY,
            )
        )
    assert store.chunks == []
