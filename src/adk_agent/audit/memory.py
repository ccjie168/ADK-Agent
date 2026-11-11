"""In-memory audit sink for local development and the console."""

from __future__ import annotations

from collections import deque

from ..core import AuditEvent


class ListAuditSink:
    """Keep the most recent audit events in memory."""

    def __init__(self, maxlen: int = 1000) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self._events: deque[AuditEvent] = deque(maxlen=maxlen)

    async def emit(self, event: AuditEvent) -> None:
        self._events.append(event)

    def recent(self, limit: int = 50) -> list[AuditEvent]:
        if limit <= 0:
            return []
        return list(self._events)[-limit:]
