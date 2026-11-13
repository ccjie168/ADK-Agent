"""Fixed-window ingress rate limiting, in-process or shared via Redis."""

from __future__ import annotations

import logging
import math
import os
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .metrics import MetricsRegistry

logger = logging.getLogger(__name__)

_DEFAULT_EXEMPT = frozenset({"/healthz"})
_MAX_KEYS = 4096

_REDIS_INCR = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RedisLimitUnavailable(RuntimeError):
    """The Redis rate-limit backend cannot be used."""


class RateLimit(BaseModel):
    """Hits a caller may make within one fixed window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit: int = Field(gt=0)
    window_seconds: float = Field(gt=0)


class FixedWindowLimiter:
    """Count hits per key and expire them in a fixed window."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Record a hit and return None, or the seconds until the key may retry."""
        now = self._clock()
        cutoff = now - self._window
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= _MAX_KEYS:
                self._sweep(cutoff)
            hits = deque(maxlen=self._limit)
            self._hits[key] = hits
        else:
            while hits and hits[0] <= cutoff:
                hits.popleft()
        if len(hits) >= self._limit:
            return max(0.0, hits[0] + self._window - now)
        hits.append(now)
        return None

    async def acheck(self, key: str) -> float | None:
        return self.check(key)

    def _sweep(self, cutoff: float) -> None:
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


class RedisFixedWindowLimiter:
    """Count hits in Redis so replicas share one window."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        url: str,
        surface: str,
        client: Any | None = None,
        clock: Callable[[], float] = time.time,
        fallback: FixedWindowLimiter | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")
        self._limit = limit
        self._window = window_seconds
        self._surface = surface
        self._clock = clock
        self._metrics = metrics
        self._fallback = fallback or FixedWindowLimiter(limit, window_seconds)
        self._warned = False
        if client is None:
            try:
                import redis.asyncio as redis_asyncio
            except ImportError:
                raise RedisLimitUnavailable(
                    "install the redis client with: pip install 'adk-agent[redis]'"
                ) from None
            client = redis_asyncio.from_url(url)
        self._client = client
        self._script = client.register_script(_REDIS_INCR)

    async def acheck(self, key: str) -> float | None:
        start = math.floor(self._clock() / self._window) * self._window
        redis_key = f"adk:rl:{self._surface}:{key}:{int(start)}"
        ttl_ms = max(1, math.ceil(self._window * 1000))
        try:
            count = await self._script(keys=[redis_key], args=[ttl_ms])
        except Exception:  # noqa: BLE001
            if self._metrics is not None:
                self._metrics.inc("adk_rate_limit_backend_errors_total", {"surface": self._surface})
            if not self._warned:
                logger.warning(
                    "rate limit backend unavailable on surface %s; falling back to per-process",
                    self._surface,
                )
                self._warned = True
            return self._fallback.check(key)
        if int(count) > self._limit:
            return max(0.0, start + self._window - self._clock())
        return None


def build_rate_limiter(
    config: RateLimit,
    *,
    surface: str,
    metrics: MetricsRegistry | None = None,
    client: Any | None = None,
) -> FixedWindowLimiter | RedisFixedWindowLimiter:
    """Use Redis when ``$RATE_LIMIT_URL`` is set, else the per-process limiter."""
    url = os.environ.get("RATE_LIMIT_URL")
    if not url:
        return FixedWindowLimiter(config.limit, config.window_seconds)
    return RedisFixedWindowLimiter(
        config.limit,
        config.window_seconds,
        url=url,
        surface=surface,
        client=client,
        metrics=metrics,
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Deny requests over the caller's limit with 429 and ``Retry-After``."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: Any,
        surface: str,
        metrics: MetricsRegistry | None = None,
        exempt: frozenset[str] = _DEFAULT_EXEMPT,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._surface = surface
        self._metrics = metrics
        self._exempt = exempt

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path not in self._exempt:
            wait = await self._check(self._key(request))
            if wait is not None:
                if self._metrics is not None:
                    self._metrics.inc("adk_http_rate_limited_total", {"surface": self._surface})
                return JSONResponse(
                    {"error": "rate_limited"},
                    status_code=429,
                    headers={"Retry-After": str(max(1, math.ceil(wait)))},
                )
        return await call_next(request)

    async def _check(self, key: str) -> float | None:
        acheck = getattr(self._limiter, "acheck", None)
        if acheck is not None:
            return await acheck(key)
        return self._limiter.check(key)

    @staticmethod
    def _key(request: Request) -> str:
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            return f"{principal.tenant}:{principal.subject}"
        client = request.client
        return client.host if client is not None else "unknown"
