"""Append-only audit store with one hash chain per tenant (ADR-0006)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path

from ..core import AuditEvent, AuditRecord
from .keyring import SigningKeyring


class AuditChainBroken(Exception):
    """A record does not link to its tenant's previous record."""

    def __init__(self, index: int, tenant: str) -> None:
        super().__init__(f"audit chain broken at record {index} for tenant {tenant!r}")
        self.index = index
        self.tenant = tenant


class AuditSignatureInvalid(Exception):
    """A record's HMAC signature is missing or does not match."""

    def __init__(self, index: int, tenant: str) -> None:
        super().__init__(f"audit signature invalid at record {index} for tenant {tenant!r}")
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


def record_signature(record_hash: str, signing_key: str) -> str:
    """HMAC-SHA256 over the record hash text, keyed by ``signing_key``."""
    return hmac.new(
        signing_key.encode("utf-8"), record_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _segment_paths(path: str | Path) -> list[Path]:
    """Archived ``.000001`` segments in order, then the current base file."""
    file = Path(path)
    archived: list[tuple[int, Path]] = []
    if file.parent.is_dir():
        prefix = file.name + "."
        for candidate in file.parent.iterdir():
            if not candidate.name.startswith(prefix):
                continue
            suffix = candidate.name[len(prefix) :]
            if suffix.isdigit():
                archived.append((int(suffix), candidate))
    archived.sort(key=lambda item: item[0])
    paths = [candidate for _, candidate in archived]
    if file.is_file():
        paths.append(file)
    return paths


def _read_segment(file: Path) -> list[AuditRecord]:
    lines = file.read_text(encoding="utf-8").splitlines()
    return [AuditRecord.model_validate_json(line) for line in lines if line.strip()]


def load_records(path: str | Path) -> list[AuditRecord]:
    records: list[AuditRecord] = []
    for segment in _segment_paths(path):
        records.extend(_read_segment(segment))
    return records


def _scan_segments(
    path: str | Path,
    signing_key: str | None = None,
    keyring: SigningKeyring | None = None,
) -> tuple[int, dict[str, str], int]:
    if signing_key is not None and keyring is not None:
        raise ValueError("pass signing_key or keyring, not both")
    file = Path(path)
    last: dict[str, str] = {}
    index = 0
    current_count = 0
    for segment in _segment_paths(file):
        records = _read_segment(segment)
        for record in records:
            tenant = record.event.tenant
            if record.prev_hash != last.get(tenant, ""):
                raise AuditChainBroken(index, tenant)
            if record_hash(record.event, record.prev_hash) != record.hash:
                raise AuditChainBroken(index, tenant)
            if keyring is not None:
                key = keyring.key_for(record.kid)
                if key is None:
                    raise AuditSignatureInvalid(index, tenant)
            elif signing_key is not None:
                if record.kid is not None:
                    raise AuditSignatureInvalid(index, tenant)
                key = signing_key
            else:
                key = None
            if key is not None:
                expected = record_signature(record.hash, key)
                if record.signature is None or not hmac.compare_digest(record.signature, expected):
                    raise AuditSignatureInvalid(index, tenant)
            last[tenant] = record.hash
            index += 1
        if segment == file:
            current_count = len(records)
    return index, last, current_count


def verify_audit_file(
    path: str | Path,
    signing_key: str | None = None,
    keyring: SigningKeyring | None = None,
) -> int:
    """Recompute every link and signature. Return the record count or raise."""
    return _scan_segments(path, signing_key, keyring)[0]


def _next_sequence(path: Path) -> int:
    sequences = [
        int(segment.name[len(path.name) + 1 :])
        for segment in _segment_paths(path)
        if segment != path
    ]
    return max(sequences, default=0) + 1


class AuditPipeline:
    """Single-writer JSONL store. Rebuilds each tenant's chain on startup."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_records: int | None = None,
        signing_key: str | None = None,
        keyring: SigningKeyring | None = None,
    ) -> None:
        if signing_key is not None and keyring is not None:
            raise ValueError("pass signing_key or keyring, not both")
        self.path = Path(path)
        self.max_records = max_records
        self.signing_key = signing_key
        self.keyring = keyring
        self._lock = asyncio.Lock()
        _, self._last, self._count = _scan_segments(self.path)
        self._next_segment = _next_sequence(self.path)

    def _rotate(self) -> None:
        if self._count <= 0:
            return
        target = self.path.with_name(f"{self.path.name}.{self._next_segment:06d}")
        os.replace(self.path, target)
        self._next_segment += 1
        self._count = 0

    async def append(self, event: AuditEvent) -> AuditRecord:
        async with self._lock:
            if (
                self.max_records is not None
                and self.path.exists()
                and self._count >= self.max_records
            ):
                self._rotate()
            prev_hash = self._last.get(event.tenant, "")
            digest = record_hash(event, prev_hash)
            signing_key: str | None
            if self.keyring is not None:
                signing_key = self.keyring.keys[self.keyring.active]
                kid = self.keyring.active
            else:
                signing_key = self.signing_key
                kid = None
            record = AuditRecord(
                event=event,
                prev_hash=prev_hash,
                hash=digest,
                signature=(
                    record_signature(digest, signing_key) if signing_key is not None else None
                ),
                kid=kid,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._last[event.tenant] = record.hash
            self._count += 1
            return record


__all__ = [
    "AuditChainBroken",
    "AuditPipeline",
    "AuditSignatureInvalid",
    "load_records",
    "record_hash",
    "record_signature",
    "verify_audit_file",
]
