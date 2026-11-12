"""Append-only JSONL audit sink for a standalone process."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..core import AuditEvent


class JsonlAuditSink:
    """Write one JSON object per line. Appends and fsyncs each event.

    The write is synchronous and short. It runs inside the event loop, which is
    acceptable for a single-process gateway until the audit pipeline split.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def emit(self, event: AuditEvent) -> None:
        payload = event.model_dump_json() + "\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())


__all__ = ["JsonlAuditSink"]
