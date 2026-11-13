"""SLICE-054: the model gateway returns 503 while the circuit is open."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelGatewayRequest,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.models.breaker import BreakerProvider
from adk_agent.models.gateway import PolicyModelGateway
from adk_agent.models.service import build_model_gateway_app
from adk_agent.resilience import CircuitBreaker


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FailingProvider:
    name = "fake"
    egress = "none"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        raise RuntimeError("provider down")


def _payload() -> dict[str, Any]:
    invocation = Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )
    return ModelGatewayRequest(
        invocation=invocation,
        request=ModelRequest(
            provider="fake", model="m", messages=[Message(role="user", content="hi")]
        ),
        policy=ModelPolicy(provider_allowlist=["fake"]),
    ).model_dump(mode="json")


def test_gateway_returns_503_when_open():
    inner = FailingProvider()
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=30.0, clock=Clock())
    provider = BreakerProvider(inner, breaker)
    app = build_model_gateway_app(PolicyModelGateway({"fake": provider}), auth_token="secret")

    async def scenario() -> list[httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            return [
                await client.post(
                    "/v1/complete",
                    json=_payload(),
                    headers={"Authorization": "Bearer secret"},
                )
                for _ in range(3)
            ]

    responses = asyncio.run(scenario())

    assert [response.status_code for response in responses] == [502, 502, 503]
    assert responses[2].json() == {"error": "model_unavailable"}
    assert inner.calls == 2
