"""SLICE-054: the breaker provider wraps a model provider."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import Message, ModelRequest, ModelResponse
from adk_agent.metrics import MetricsRegistry
from adk_agent.models.breaker import BreakerProvider
from adk_agent.models.gateway import ModelUnavailable
from adk_agent.resilience import CircuitBreaker


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeProvider:
    name = "fake"
    egress = "none"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            egress="none",
        )


def _request() -> ModelRequest:
    return ModelRequest(provider="fake", model="m", messages=[Message(role="user", content="hi")])


def _provider(inner: FakeProvider, clock: Clock, *, metrics=None) -> BreakerProvider:
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=30.0, clock=clock)
    return BreakerProvider(inner, breaker, metrics=metrics)


def test_short_circuits_after_threshold():
    inner = FakeProvider(RuntimeError("down"))
    provider = _provider(inner, Clock())

    with pytest.raises(RuntimeError):
        asyncio.run(provider.complete(_request()))
    with pytest.raises(RuntimeError):
        asyncio.run(provider.complete(_request()))
    with pytest.raises(ModelUnavailable):
        asyncio.run(provider.complete(_request()))

    assert inner.calls == 2


def test_short_circuit_metric():
    inner = FakeProvider(RuntimeError("down"))
    metrics = MetricsRegistry()
    provider = _provider(inner, Clock(), metrics=metrics)

    async def scenario() -> None:
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await provider.complete(_request())
        with pytest.raises(ModelUnavailable):
            await provider.complete(_request())

    asyncio.run(scenario())
    assert 'adk_model_breaker_short_circuits_total{provider="fake"} 1' in metrics.render()


def test_recovers_after_reset():
    clock = Clock()
    inner = FakeProvider(RuntimeError("down"))
    provider = _provider(inner, clock)

    async def scenario() -> ModelResponse:
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await provider.complete(_request())
        inner.error = None
        clock.now += 30
        return await provider.complete(_request())

    response = asyncio.run(scenario())

    assert response.text == "ok"
    assert inner.calls == 3
    assert provider._breaker.state == "closed"


def test_success_passes_through():
    inner = FakeProvider()
    provider = _provider(inner, Clock())

    response = asyncio.run(provider.complete(_request()))

    assert response.text == "ok"
    assert provider.name == "fake"
    assert provider.egress == "none"
