"""Poll decided approvals and resume deferred plans once per decision (ADR-0049)."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .approvals import ApprovalHistoryEntry

logger = logging.getLogger(__name__)

_RESUMABLE = frozenset({"approved", "denied", "expired"})

__all__ = ["ApprovalResumer"]


class ApprovalResumer:
    """Call ``handler`` exactly once for every decided approval it observes.

    The resumer keeps the request ids it has handled in memory. A handler
    error is logged and counted, and that request is not retried; operators
    see the count and the plan stays at its checkpoint for a manual retry.
    """

    def __init__(
        self,
        inbox: Any,
        handler: Callable[[ApprovalHistoryEntry], Awaitable[None] | None],
        *,
        poll_seconds: float = 1.0,
        batch: int = 50,
    ) -> None:
        if getattr(inbox, "history", None) is None:
            raise ValueError("approval inbox must provide history()")
        self.inbox = inbox
        self.handler = handler
        self.poll_seconds = max(0.05, poll_seconds)
        self.batch = max(1, min(200, batch))
        self._seen: set[str] = set()
        self._stop = asyncio.Event()
        self.handled = 0
        self.failed = 0

    async def run_once(self) -> int:
        entries = self.inbox.history(limit=self.batch)
        if inspect.isawaitable(entries):
            entries = await entries
        handled = 0
        for entry in entries or ():
            request_id = entry.request.request_id
            if request_id in self._seen or entry.status not in _RESUMABLE:
                continue
            self._seen.add(request_id)
            try:
                result = self.handler(entry)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001  # one plan must not stall the loop
                self.failed += 1
                logger.warning("approval resume failed for %s", request_id, exc_info=True)
                continue
            self.handled += 1
            handled += 1
        return handled

    async def run_forever(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  # a broken store should not kill the loop
                logger.warning("approval resumer poll failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
