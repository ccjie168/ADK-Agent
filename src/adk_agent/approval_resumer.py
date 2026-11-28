"""Poll decided approvals and resume deferred plans once per decision (ADR-0049)."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .approvals import ApprovalHistoryEntry

logger = logging.getLogger(__name__)

_RESUMABLE = frozenset({"approved", "denied"})
_SKIPPED = frozenset({"expired"})
_TERMINAL = _RESUMABLE | _SKIPPED
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

__all__ = ["ApprovalResumer"]


class ApprovalResumer:
    """Call ``handler`` exactly once for every decided approval it observes.

    The resumer keeps the request ids it has handled in memory. A handler
    error is logged and counted, and that request is not retried; operators
    see the count and the plan stays at its checkpoint for a manual retry.

    ``expired`` decisions are marked as seen but never handed to the handler:
    ADR-0049 says an expired request is not resumed. ``history`` is read
    oldest-first so a burst larger than ``batch`` is drained across polls
    instead of the newest entries hiding the oldest.
    """

    def __init__(
        self,
        inbox: Any,
        handler: Callable[[ApprovalHistoryEntry], Awaitable[None] | None],
        *,
        poll_seconds: float = 1.0,
        batch: int = 50,
        claim_dir: str | Path | None = None,
    ) -> None:
        if getattr(inbox, "history", None) is None:
            raise ValueError("approval inbox must provide history()")
        self.inbox = inbox
        self.handler = handler
        self.poll_seconds = max(0.05, poll_seconds)
        self.batch = max(1, min(200, batch))
        self._seen: dict[str, None] = {}
        self.max_seen = 10_000
        self._watermark: datetime | None = None
        self.claim_dir = Path(claim_dir) if claim_dir is not None else None
        self.skipped = 0
        self._stop = asyncio.Event()
        self.handled = 0
        self.failed = 0

    async def run_once(self) -> int:
        entries = self.inbox.history(limit=self.batch, oldest_first=True, since=self._watermark)
        if inspect.isawaitable(entries):
            entries = await entries
        handled = 0
        for entry in entries or ():
            request_id = entry.request.request_id
            if request_id in self._seen or entry.status not in _TERMINAL:
                continue
            self._remember(request_id)
            if self._watermark is None or entry.terminal_at > self._watermark:
                self._watermark = entry.terminal_at
            if entry.status in _SKIPPED:
                continue
            if not self._claim(request_id):
                self.skipped += 1
                continue
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

    def _claim(self, request_id: str) -> bool:
        """Take a per-request lock file so two resumers never both resume."""
        if self.claim_dir is None:
            return True
        if not _SAFE_ID.match(request_id):
            raise ValueError("request id is not safe for a claim file")
        self.claim_dir.mkdir(parents=True, exist_ok=True)
        path = self.claim_dir / f".resume-{request_id}.lock"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.close(fd)
        return True

    def _remember(self, request_id: str) -> None:
        self._seen[request_id] = None
        if len(self._seen) > self.max_seen:
            self._seen.pop(next(iter(self._seen)))

    async def run_forever(self) -> None:
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
