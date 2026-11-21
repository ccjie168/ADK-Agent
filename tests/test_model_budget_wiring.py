"""SLICE-210: the model gateway service enforces the resolved policy budget."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent import cli
from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.models.budget import BudgetTracker
from adk_agent.models.gateway import ModelDenied

_COST = 1.0
_BUDGET = 1.0


class CostProvider:
    name = "fake"
    egress = "third_party"

    def __init__(self, cost: float) -> None:
        self.cost = cost
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            cost_usd=self.cost,
            egress="third_party",
        )


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request() -> ModelRequest:
    return ModelRequest(provider="fake", model="m1", messages=[Message(role="user", content="hi")])


def _serve(monkeypatch, provider: CostProvider):
    captured: dict = {}
    monkeypatch.setattr(
        "adk_agent.models.service.build_providers",
        lambda names, *, vllm_url=None: {"fake": provider},
    )

    def fake_build_app(gateway, **kwargs):
        captured["gateway"] = gateway
        return object()

    monkeypatch.setattr("adk_agent.models.service.build_model_gateway_app", fake_build_app)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    cli.main(["serve-model-gateway", "--provider", "fake", "--allow-unauthenticated"])
    return captured["gateway"]


def test_serve_model_gateway_enforces_budget(monkeypatch):
    provider = CostProvider(_COST)
    gateway = _serve(monkeypatch, provider)
    policy = ModelPolicy(provider_allowlist=["fake"], budget_usd=_BUDGET)

    asyncio.run(gateway.complete(_invocation(), _request(), policy))
    assert provider.calls == 1

    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request(), policy))
    assert provider.calls == 1


def test_build_rag_factory_shares_budget_tracker():
    from adk_agent.rag.factory import build_rag_factory

    tracker = BudgetTracker()
    factory = build_rag_factory(
        database_url="postgresql://u@127.0.0.1:1/x",
        dimensions=8,
        model="text-embedding-3-small",
        budgets=tracker,
    )

    assert factory.gateway.budgets is tracker
