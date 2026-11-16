"""File-backed tool grant requests. One JSON file per request."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..core import (
    GrantRequestConflict,
    GrantRequestExpired,
    GrantRequestNotFound,
    GrantStatus,
    GrantStoreError,
    ToolGrantRequest,
    effective_status,
)
from .paths import safe_join

_REQUEST_FILE = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json$"


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


class FileToolGrantStore:
    """Store grant requests under ``<root>/<request_id>.json`` for single-host dev."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, request_id: str) -> Path:
        return safe_join(self.root, f"{request_id}.json", pattern=_REQUEST_FILE)

    async def add(self, request: ToolGrantRequest) -> ToolGrantRequest:
        path = self._path(request.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, request)
            payload = json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            try:
                os.link(tmp_path, path)
            except FileExistsError:
                return self._resolve_existing(path, request)
            finally:
                tmp_path.unlink(missing_ok=True)
        return request

    async def get(self, request_id: str) -> ToolGrantRequest | None:
        path = self._path(request_id)
        if not path.is_file():
            return None
        return self._load(path)

    async def list(
        self,
        tenant: str,
        *,
        status: GrantStatus | None = None,
        now: datetime | None = None,
    ) -> list[ToolGrantRequest]:
        moment = _now(now)
        if not self.root.is_dir():
            return []
        records: list[ToolGrantRequest] = []
        for path in self.root.glob("*.json"):
            record = self._load(path)
            if record.tenant != tenant:
                continue
            if status is not None and effective_status(record, moment) != status:
                continue
            records.append(record)
        records.sort(key=lambda record: (record.requested_at, record.request_id))
        return records

    async def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> ToolGrantRequest:
        moment = _now(now)
        with self._lock:
            record = self._get_existing(request_id)
            self._require_changeable(record, moment)
            decided = record.model_copy(
                update={
                    "status": "approved" if approved else "denied",
                    "decided_by": decided_by,
                    "decided_at": moment,
                    "decision_reason": reason,
                }
            )
            self._write(decided)
            return decided

    async def cancel(
        self,
        request_id: str,
        *,
        by: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> ToolGrantRequest:
        moment = _now(now)
        with self._lock:
            record = self._get_existing(request_id)
            self._require_changeable(record, moment)
            cancelled = record.model_copy(
                update={
                    "status": "cancelled",
                    "decided_by": by,
                    "decided_at": moment,
                    "decision_reason": reason,
                }
            )
            self._write(cancelled)
            return cancelled

    async def active(
        self,
        tenant: str,
        agent_id: str,
        version: str,
        digest: str,
        tool_id: str,
        now: datetime | None = None,
    ) -> bool:
        moment = _now(now)
        if not self.root.is_dir():
            return False
        for path in self.root.glob("*.json"):
            record = self._load(path)
            if (
                record.tenant == tenant
                and record.agent_id == agent_id
                and record.version == version
                and record.digest == digest
                and record.tool_id == tool_id
                and effective_status(record, moment) == "approved"
            ):
                return True
        return False

    def _get_existing(self, request_id: str) -> ToolGrantRequest:
        path = self._path(request_id)
        if not path.is_file():
            raise GrantRequestNotFound(f"tool grant request {request_id!r} not found")
        return self._load(path)

    def _require_changeable(self, record: ToolGrantRequest, now: datetime) -> None:
        effective = effective_status(record, now)
        if effective == "expired":
            raise GrantRequestExpired(f"tool grant request {record.request_id!r} is expired")
        if effective != "pending":
            raise GrantRequestConflict(f"tool grant request {record.request_id!r} is {effective}")

    def _write(self, record: ToolGrantRequest) -> None:
        path = self._path(record.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _load(self, path: Path) -> ToolGrantRequest:
        try:
            return ToolGrantRequest.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise GrantStoreError(f"{path}: invalid tool grant record") from exc

    def _resolve_existing(self, path: Path, request: ToolGrantRequest) -> ToolGrantRequest:
        existing = self._load(path)
        if existing.model_dump(mode="json") != request.model_dump(mode="json"):
            raise GrantRequestConflict(
                f"tool grant request {request.request_id!r} already exists with different content"
            )
        return existing


__all__ = ["FileToolGrantStore"]
