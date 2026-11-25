"""Encrypted model provider keys under a store root (ADR-0045 option B).

Only ciphertext and a mask live on disk. The plaintext key is never written
here; callers wrap it with a key backend before ``put``.
"""

from __future__ import annotations

import builtins
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import UnsafePath, safe_join

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")


class FileModelProviderKeyStore:
    """Store one wrapped key per provider under ``<root>/keys``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root) / "keys"

    def _path(self, provider_id: str) -> Path:
        if _SAFE_ID.fullmatch(provider_id) is None:
            raise UnsafePath(f"unsafe provider id {provider_id!r}")
        return safe_join(self.root, f"{provider_id}.json")

    async def get(self, provider_id: str) -> dict[str, Any] | None:
        path = self._path(provider_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("wrapped_secret"), dict):
            raise ValueError("malformed model key record")
        return payload

    async def hints(self) -> builtins.dict[str, dict[str, Any]]:
        if not self.root.is_dir():
            return {}
        hints: dict[str, dict[str, Any]] = {}
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            provider_id = payload.get("provider_id") if isinstance(payload, dict) else None
            hint = payload.get("hint") if isinstance(payload, dict) else None
            if isinstance(provider_id, str) and isinstance(hint, str):
                hints[provider_id] = {"hint": hint, "updated_at": payload.get("updated_at")}
        return hints

    async def put(
        self,
        provider_id: str,
        wrapped: Mapping[str, Any],
        *,
        key_id: str,
        hint: str,
        updated_by: str = "",
    ) -> dict[str, Any]:
        path = self._path(provider_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = {
            "provider_id": provider_id,
            "wrapped_secret": dict(wrapped),
            "key_id": key_id,
            "hint": hint,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }
        payload = json.dumps(stored, indent=2, sort_keys=True) + "\n"
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
        return stored

    async def delete(self, provider_id: str) -> bool:
        path = self._path(provider_id)
        existed = path.is_file()
        path.unlink(missing_ok=True)
        return existed


__all__ = ["FileModelProviderKeyStore"]
