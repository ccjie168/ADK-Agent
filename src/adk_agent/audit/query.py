"""Read access to a shared audit store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..core import AuditEvent
from .pipeline import query_events


class AuditQuery(Protocol):
    """Read recent audit events for one tenant or for every tenant."""

    async def events(
        self,
        *,
        tenant: str | None,
        limit: int,
        before: tuple[datetime, str] | None = None,
    ) -> list[AuditEvent]: ...

    async def aclose(self) -> None: ...


class FileAuditQuery:
    """Query audit events from a local JSONL audit file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def events(
        self,
        *,
        tenant: str | None,
        limit: int,
        before: tuple[datetime, str] | None = None,
    ) -> list[AuditEvent]:
        return query_events(self.path, tenant=tenant, limit=limit, order="desc", before=before)

    async def aclose(self) -> None:
        pass


__all__ = ["AuditQuery", "FileAuditQuery"]
