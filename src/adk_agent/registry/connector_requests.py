"""File-backed connector registration requests. One JSON file per request."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..core import (
    ConnectorRequest,
    ConnectorRequestConflict,
    ConnectorRequestError,
    ConnectorRequestNotFound,
    ConnectorRequestStatus,
)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


class FileConnectorRequestStore:
    """Store connector requests under ``<root>/<request_id>.json`` for single-host dev."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, request_id: str) -> Path:
        if not _REQUEST_ID.fullmatch(request_id):
            raise ValueError(f"unsafe connector request id {request_id!r}")
        return self.root / f"{request_id}.json"

    async def add(self, record: ConnectorRequest) -> ConnectorRequest:
        path = self._path(record.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, record)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(self._payload(record))
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            try:
                os.link(tmp_path, path)
            except FileExistsError:
                return self._resolve_existing(path, record)
            finally:
                tmp_path.unlink(missing_ok=True)
        return record

    async def get(self, request_id: str) -> ConnectorRequest | None:
        path = self._path(request_id)
        if not path.is_file():
            return None
        return self._load(path)

    async def list(
        self,
        tenant: str,
        *,
        status: ConnectorRequestStatus | None = None,
    ) -> list[ConnectorRequest]:
        if not self.root.is_dir():
            return []
        records: list[ConnectorRequest] = []
        for path in self.root.glob("*.json"):
            record = self._load(path)
            if record.tenant != tenant:
                continue
            if status is not None and record.status != status:
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
        registered_connector: str | None = None,
        now: datetime | None = None,
    ) -> ConnectorRequest:
        moment = _now(now)
        with self._lock:
            record = self._get_existing(request_id)
            if record.status != "pending":
                raise ConnectorRequestConflict(
                    f"connector request {request_id!r} is {record.status}"
                )
            decided = record.model_copy(
                update={
                    "status": "approved" if approved else "denied",
                    "decided_by": decided_by,
                    "decided_at": moment,
                    "decision_reason": reason,
                    "registered_connector": registered_connector if approved else None,
                }
            )
            self._write(decided)
            return decided

    def _get_existing(self, request_id: str) -> ConnectorRequest:
        path = self._path(request_id)
        if not path.is_file():
            raise ConnectorRequestNotFound(f"connector request {request_id!r} not found")
        return self._load(path)

    def _payload(self, record: ConnectorRequest) -> str:
        return json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

    def _write(self, record: ConnectorRequest) -> None:
        path = self._path(record.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(self._payload(record))
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _load(self, path: Path) -> ConnectorRequest:
        try:
            return ConnectorRequest.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConnectorRequestError(f"{path}: invalid connector request record") from exc

    def _resolve_existing(self, path: Path, record: ConnectorRequest) -> ConnectorRequest:
        existing = self._load(path)
        if existing.model_dump(mode="json") != record.model_dump(mode="json"):
            raise ConnectorRequestConflict(
                f"connector request {record.request_id!r} already exists with different content"
            )
        return existing


__all__ = ["FileConnectorRequestStore"]
