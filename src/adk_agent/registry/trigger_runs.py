"""File-backed trigger fire records for single-host development (SLICE-125)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..core import TriggerFire, TriggerFireConflict, TriggerFireError, TriggerFireStatus
from .paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TRIGGER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class FileTriggerFireStore:
    """One fire per ``(tenant, trigger_id, idempotency_key)``.

    Layout: ``<root>/<tenant>/<trigger_id>/<sha256(key)>.json``. Claiming links a
    fully written temp file into place, so concurrent callers get one winner.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, tenant: str, trigger_id: str, idempotency_key: str) -> Path:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ValueError(f"unsafe idempotency key {idempotency_key!r}")
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        tenant_dir = safe_join(self.root, tenant, pattern=_NAME.pattern)
        trigger_dir = safe_join(tenant_dir, trigger_id, pattern=_TRIGGER_ID.pattern)
        return safe_join(trigger_dir, f"{digest}.json")

    async def claim(self, fire: TriggerFire) -> TriggerFire:
        path = self._path(fire.tenant, fire.trigger_id, fire.idempotency_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.is_file():
                return self._read(path)
            payload = json.dumps(fire.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
        return fire

    async def finish(
        self,
        tenant: str,
        trigger_id: str,
        idempotency_key: str,
        *,
        status: TriggerFireStatus,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> TriggerFire:
        path = self._path(tenant, trigger_id, idempotency_key)
        with self._lock:
            if not path.is_file():
                raise TriggerFireConflict(
                    f"trigger fire not found: {tenant}/{trigger_id}/{idempotency_key}"
                )
            existing = self._read(path)
            updated = existing.model_copy(
                update={
                    "status": status,
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

    async def get(self, tenant: str, trigger_id: str, idempotency_key: str) -> TriggerFire | None:
        path = self._path(tenant, trigger_id, idempotency_key)
        if not path.is_file():
            return None
        return self._read(path)

    def _read(self, path: Path) -> TriggerFire:
        try:
            return TriggerFire.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise TriggerFireError(f"{path.name}: invalid trigger fire record") from exc


__all__ = ["FileTriggerFireStore"]
