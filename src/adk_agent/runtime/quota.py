"""In-process per-tenant quota manager."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from types import TracebackType

from ..core import QuotaExceeded, QuotaPolicy, QuotaUsage


class InMemoryQuotaManager:
    """Fixed-window run counts and concurrent-run caps per tenant.

    State is process-local. Multi-replica deployments need a shared backend.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._windows: dict[str, deque[float]] = {}
        self._active: dict[str, int] = {}

    def reserve(self, tenant: str, policy: QuotaPolicy) -> _Reservation:
        return _Reservation(self, tenant, policy)

    async def _enter(self, tenant: str, policy: QuotaPolicy) -> None:
        async with self._lock:
            now = self._clock()
            window = self._windows.setdefault(tenant, deque())
            if policy.max_runs is not None:
                cutoff = now - policy.window_seconds
                while window and window[0] <= cutoff:
                    window.popleft()
                if len(window) >= policy.max_runs:
                    raise QuotaExceeded(tenant, "max_runs")
            if (
                policy.max_concurrent is not None
                and self._active.get(tenant, 0) >= policy.max_concurrent
            ):
                raise QuotaExceeded(tenant, "max_concurrent")

            if policy.max_runs is not None:
                window.append(now)
            if policy.max_concurrent is not None:
                self._active[tenant] = self._active.get(tenant, 0) + 1

    async def _exit(self, tenant: str, policy: QuotaPolicy) -> None:
        if policy.max_concurrent is None:
            return
        async with self._lock:
            self._active[tenant] = max(0, self._active.get(tenant, 0) - 1)

    async def usage(self, tenant: str, policy: QuotaPolicy) -> QuotaUsage:
        async with self._lock:
            now = self._clock()
            window = self._windows.get(tenant, deque())
            if policy.max_runs is not None:
                cutoff = now - policy.window_seconds
                while window and window[0] <= cutoff:
                    window.popleft()
            return QuotaUsage(
                window_runs=len(window),
                active_leases=self._active.get(tenant, 0),
                max_runs=policy.max_runs,
                max_concurrent=policy.max_concurrent,
                window_seconds=policy.window_seconds,
            )


class _Reservation:
    def __init__(self, manager: InMemoryQuotaManager, tenant: str, policy: QuotaPolicy) -> None:
        self._manager = manager
        self._tenant = tenant
        self._policy = policy
        self._held = False

    async def __aenter__(self) -> None:
        await self._manager._enter(self._tenant, self._policy)
        self._held = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._held:
            self._held = False
            await self._manager._exit(self._tenant, self._policy)


__all__ = ["InMemoryQuotaManager", "QuotaExceeded"]
