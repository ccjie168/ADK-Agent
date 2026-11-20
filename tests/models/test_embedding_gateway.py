"""SLICE-190: embedding port, gateway budget check, and model.embed audit (ADR-0035 slice 2)."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import (
    AgentRef,
    AuditEvent,
    EmbeddingRequest,
    EmbeddingResponse,
    Invocation,
    ModelPolicy,
    Principal,
)
from adk_agent.models.budget import BudgetTracker
from adk_agent.models.embeddings import EmbeddingGateway
from adk_agent.models.gateway import ModelDenied


def _policy(*, allowlist=("fake",), budget: float | None = None) -> ModelPolicy:
    return ModelPolicy(provider_allowlist=list(allowlist), budget_usd=budget)


def _invocation(tenant: str = "t1") -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request() -> EmbeddingRequest:
    return EmbeddingRequest(provider="fake", model="embed-model", texts=["a", "b"])


class FakeEmbeddingProvider:
    def __init__(self, *, cost: float | None = 0.2) -> None:
        self.name = "fake"
        self.egress = "third_party"
        self.cost = cost
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        return EmbeddingResponse(
            vectors=[[0.1, 0.2] for _ in request.texts],
            model=request.model,
            input_tokens=2,
            cost_usd=self.cost,
            egress="third_party",
        )


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def test_embedding_gateway_returns_vectors():
    provider = FakeEmbeddingProvider()
    gateway = EmbeddingGateway({"fake": provider})
    response = asyncio.run(gateway.embed(_invocation(), _request(), _policy()))
    assert response.vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert len(provider.requests) == 1


def test_embedding_gateway_rejects_unlisted_provider():
    with pytest.raises(ModelDenied):
        asyncio.run(
            EmbeddingGateway({"fake": FakeEmbeddingProvider()}).embed(
                _invocation(), _request(), _policy(allowlist=("other",))
            )
        )


def test_embedding_gateway_denies_over_budget():
    provider = FakeEmbeddingProvider()
    budgets = BudgetTracker()
    budgets.add("t1", 1.0)
    gateway = EmbeddingGateway({"fake": provider}, budgets=budgets)
    with pytest.raises(ModelDenied):
        asyncio.run(gateway.embed(_invocation(), _request(), _policy(budget=1.0)))
    assert provider.requests == []


def test_embedding_gateway_accumulates_cost():
    budgets = BudgetTracker()
    gateway = EmbeddingGateway({"fake": FakeEmbeddingProvider(cost=0.3)}, budgets=budgets)
    asyncio.run(gateway.embed(_invocation(), _request(), _policy(budget=10.0)))
    assert budgets.spent("t1") == pytest.approx(0.3)


def test_embedding_gateway_audits_call():
    audit = RecordingAudit()
    gateway = EmbeddingGateway({"fake": FakeEmbeddingProvider()}, audit=audit)
    asyncio.run(gateway.embed(_invocation(), _request(), _policy()))
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.action == "model.embed"
    assert event.target == "fake:embed-model"
    assert event.status == "ok"
    assert event.egress == "third_party"
