"""SLICE-187: per-tenant model budget enforcement (ADR-0033 slice 3)."""

from __future__ import annotations

import asyncio

import pytest

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
from adk_agent.models.gateway import ModelDenied, PolicyModelGateway


def _policy(budget: float | None = 1.0) -> ModelPolicy:
    return ModelPolicy(provider_allowlist=["fake"], budget_usd=budget)


def _invocation(tenant: str = "t1") -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request() -> ModelRequest:
    return ModelRequest(provider="fake", model="m1", messages=[Message(role="user", content="hi")])


class FakeProvider:
    name = "fake"
    egress = "third_party"

    def __init__(self, cost: float | None = 0.4) -> None:
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


def test_budget_allows_and_accumulates():
    provider = FakeProvider(cost=0.4)
    budgets = BudgetTracker()
    gateway = PolicyModelGateway({"fake": provider}, budgets=budgets)
    asyncio.run(gateway.complete(_invocation(), _request(), _policy()))
    assert budgets.spent("t1") == pytest.approx(0.4)
    asyncio.run(gateway.complete(_invocation(), _request(), _policy()))
    assert budgets.spent("t1") == pytest.approx(0.8)


def test_budget_denies_at_limit():
    budgets = BudgetTracker()
    budgets.add("t1", 1.0)
    gateway = PolicyModelGateway({"fake": FakeProvider()}, budgets=budgets)
    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request(), _policy()))


def test_budget_denial_skips_provider():
    provider = FakeProvider()
    budgets = BudgetTracker()
    budgets.add("t1", 5.0)
    gateway = PolicyModelGateway({"fake": provider}, budgets=budgets)
    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request(), _policy()))
    assert provider.calls == 0


def test_no_tracker_no_enforcement():
    budgets_spent = BudgetTracker()
    budgets_spent.add("t1", 100.0)
    provider = FakeProvider()
    gateway = PolicyModelGateway({"fake": provider})
    response = asyncio.run(gateway.complete(_invocation(), _request(), _policy(budget=0.01)))
    assert response.text == "ok"
    assert provider.calls == 1


def test_budget_is_per_tenant():
    budgets = BudgetTracker()
    budgets.add("t1", 1.0)
    provider = FakeProvider()
    gateway = PolicyModelGateway({"fake": provider}, budgets=budgets)
    response = asyncio.run(gateway.complete(_invocation("t2"), _request(), _policy()))
    assert response.text == "ok"
    assert budgets.spent("t2") == pytest.approx(0.4)
