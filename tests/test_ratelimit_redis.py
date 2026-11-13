"""SLICE-084: Redis-backed shared rate limiting (ADR-0012)."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adk_agent.metrics import MetricsRegistry
from adk_agent.ratelimit import (
    FixedWindowLimiter,
    RateLimit,
    RateLimitMiddleware,
    RedisFixedWindowLimiter,
    build_rate_limiter,
)


class FakeRedis:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.values: dict[str, int] = {}
        self.error = error

    def register_script(self, script: str):
        return self._call

    async def _call(self, keys, args):
        if self.error is not None:
            raise self.error
        key = keys[0]
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]


def _limiter(client: FakeRedis, *, limit: int = 2, fallback=None, metrics=None):
    return RedisFixedWindowLimiter(
        limit,
        60,
        url="redis://localhost",
        surface="console",
        client=client,
        clock=lambda: 1000.0,
        fallback=fallback,
        metrics=metrics,
    )


def test_redis_limiter_counts_shared():
    client = FakeRedis()
    first = _limiter(client)
    second = _limiter(client)

    assert asyncio.run(first.acheck("t1:alice")) is None
    assert asyncio.run(second.acheck("t1:alice")) is None
    wait = asyncio.run(first.acheck("t1:alice"))

    assert wait is not None and wait > 0
    [key] = client.values
    assert key.startswith("adk:rl:console:t1:alice:")


def test_redis_limiter_fail_open():
    client = FakeRedis(error=ConnectionError("down"))
    fallback = FixedWindowLimiter(1, 60)
    limiter = _limiter(client, limit=1, fallback=fallback)

    assert asyncio.run(limiter.acheck("k")) is None
    assert asyncio.run(limiter.acheck("k")) is not None


def test_backend_error_metric():
    metrics = MetricsRegistry()
    client = FakeRedis(error=ConnectionError("down"))
    limiter = _limiter(client, fallback=FixedWindowLimiter(100, 60), metrics=metrics)

    asyncio.run(limiter.acheck("k"))

    assert 'adk_rate_limit_backend_errors_total{surface="console"} 1' in metrics.render()


class AsyncLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acheck(self, key: str) -> float | None:
        self.calls += 1
        return None if self.calls == 1 else 7.0


def test_middleware_awaits_async_limiter():
    limiter = AsyncLimiter()
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, limiter=limiter, surface="test")
    with TestClient(app) as client:
        first = client.get("/ping")
        second = client.get("/ping")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "7"


def test_build_rate_limiter_selects_backend(monkeypatch):
    config = RateLimit(limit=5, window_seconds=60)
    monkeypatch.delenv("RATE_LIMIT_URL", raising=False)
    assert isinstance(build_rate_limiter(config, surface="console"), FixedWindowLimiter)

    monkeypatch.setenv("RATE_LIMIT_URL", "redis://localhost")
    redis_limiter = build_rate_limiter(config, surface="console", client=FakeRedis())
    assert isinstance(redis_limiter, RedisFixedWindowLimiter)
