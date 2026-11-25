"""File-backed model provider store (ADR-0045)."""

from __future__ import annotations

import builtins
import json
import os
import re
import tempfile
from pathlib import Path

from ..core import ModelProviderRecord
from .paths import UnsafePath, safe_join

_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"


class FileModelProviderStore:
    """Store provider records under ``<root>/<provider_id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, provider_id: str) -> Path:
        if re.fullmatch(_SAFE_ID, provider_id) is None:
            raise UnsafePath(f"unsafe provider id {provider_id!r}")
        return safe_join(self.root, f"{provider_id}.json")

    async def get(self, provider_id: str) -> ModelProviderRecord | None:
        path = self._path(provider_id)
        if not path.is_file():
            return None
        return ModelProviderRecord.model_validate_json(path.read_text(encoding="utf-8"))

    async def list(self) -> builtins.list[ModelProviderRecord]:
        if not self.root.is_dir():
            return []
        records = [
            ModelProviderRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob("*.json"))
        ]
        records.sort(key=lambda record: record.provider_id)
        return records

    async def put(self, provider: ModelProviderRecord) -> ModelProviderRecord:
        path = self._path(provider.provider_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(provider.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
        return provider
