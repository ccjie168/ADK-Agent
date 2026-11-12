"""Append-only audit store with one hash chain per tenant (ADR-0006)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from ..core import AuditEvent, AuditRecord


class AuditChainBroken(Exception):
    """A record does not link to its tenant's previous record."""

    def __init__(self, index: int, tenant: str) -> None:
        super().__init__(f"audit chain broken at record {index} for tenant {tenant!r}")
        self.index = index
        self.tenant = tenant


def record_hash(event: AuditEvent, prev_hash: str) -> str:
    canonical = json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(f"{prev_hash}\n{canonical}".encode()).hexdigest()


def load_records(path: str | Path) -> list[AuditRecord]:
    file = Path(path)
    if not file.is_file():
        return []
    lines = file.read_text(encoding="utf-8").splitlines()
    return [AuditRecord.model_validate_json(line) for line in lines if line.strip()]


def _scan(path: Path) -> tuple[int, dict[str, str]]:
    last: dict[str, str] = {}
    records = load_records(path)
    for index, record in enumerate(records):
        tenant = record.event.tenant
        if record.prev_hash != last.get(tenant, ""):
            raise AuditChainBroken(index, tenant)
        if record_hash(record.event, record.prev_hash) != record.hash:
            raise AuditChainBroken(index, tenant)
        last[tenant] = record.hash
    return len(records), last


def verify_audit_file(path: str | Path) -> int:
    """Recompute every link. Return the record count or raise AuditChainBroken."""
    return _scan(Path(path))[0]


class AuditPipeline:
    """Single-writer JSONL store. Rebuilds each tenant's chain on startup."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        _, self._last = _scan(self.path)

    async def append(self, event: AuditEvent) -> AuditRecord:
        async with self._lock:
            prev_hash = self._last.get(event.tenant, "")
            record = AuditRecord(
                event=event,
                prev_hash=prev_hash,
                hash=record_hash(event, prev_hash),
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._last[event.tenant] = record.hash
            return record


__all__ = [
    "AuditChainBroken",
    "AuditPipeline",
    "load_records",
    "record_hash",
    "verify_audit_file",
]
