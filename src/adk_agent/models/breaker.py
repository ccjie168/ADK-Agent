"""A model provider decorator that fails fast while its circuit is open."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ..core import ModelProvider, ModelRequest, ModelResponse
from ..resilience import CircuitBreaker
from .gateway import ModelUnavailable

if TYPE_CHECKING:  # pragma: no cover
    from ..metrics import MetricsRegistry

__all__ = ["BreakerProvider"]


class BreakerProvider:
    """Wrap a provider so repeated failures short-circuit calls to it."""

    def __init__(
        self,
        inner: ModelProvider,
        breaker: CircuitBreaker,
        *,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._inner = inner
        self._breaker = breaker
        self._metrics = metrics

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def egress(self) -> Literal["none", "third_party"]:
        return self._inner.egress

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self._breaker.allow():
            if self._metrics is not None:
                self._metrics.inc(
                    "adk_model_breaker_short_circuits_total",
                    {"provider": self.name},
                )
            raise ModelUnavailable(f"provider {self.name!r} circuit is open")
        try:
            response = await self._inner.complete(request)
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return response
