"""File-backed tool idempotency records (ADR-0034)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core import (
    DataClass,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolIdempotencyConflict,
    ToolIdempotencyError,
)
from ..registry.paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TOOL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class FileToolIdempotencyStore:
    """One execution record per ``(tenant, tool_id, idempotency_key)``.

    Layout: ``<root>/<tenant>/<tool_id>/<sha256(key)>.json``. Claiming links a
    fully written temp file into place, so concurrent callers get one winner.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, tenant: str, tool_id: str, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        tenant_dir = safe_join(self.root, tenant, pattern=_NAME.pattern)
        tool_dir = safe_join(tenant_dir, tool_id, pattern=_TOOL_ID.pattern)
        return safe_join(tool_dir, f"{digest}.json")

    async def claim(self, record: ToolExecutionRecord) -> ToolExecutionRecord:
        path = self._path(record.tenant, record.tool_id, record.idempotency_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.is_file():
                return self._read(path)
            payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
                return self._read(path)
            finally:
                tmp_path.unlink(missing_ok=True)
        return record

    async def finish(
        self,
        tenant: str,
        tool_id: str,
        idempotency_key: str,
        *,
        status: ToolExecutionStatus,
        output: Any = None,
        data_classes: list[DataClass] | None = None,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> ToolExecutionRecord:
        path = self._path(tenant, tool_id, idempotency_key)
        with self._lock:
            if not path.is_file():
                raise ToolIdempotencyConflict(
                    f"tool execution not found: {tenant}/{tool_id}/{idempotency_key}"
                )
            existing = self._read(path)
            updated = existing.model_copy(
                update={
                    "status": status,
                    "output": output,
                    "data_classes": list(data_classes) if data_classes is not None else [],
                    "error_code": error_code,
                    "finished_at": finished_at or datetime.now(timezone.utc),
                }
            )
            payload = json.dumps(updated.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
        return updated

    async def get(
        self, tenant: str, tool_id: str, idempotency_key: str
    ) -> ToolExecutionRecord | None:
        path = self._path(tenant, tool_id, idempotency_key)
        if not path.is_file():
            return None
        return self._read(path)

    async def aclose(self) -> None:
        return None

    def _read(self, path: Path) -> ToolExecutionRecord:
        try:
            return ToolExecutionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ToolIdempotencyError(f"{path.name}: invalid tool execution record") from exc


__all__ = ["FileToolIdempotencyStore"]
