"""File-backed global default model config for single-host development."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from ..models.config_store import ModelConfigStoreUnavailable


class FileModelConfigStore:
    """One global default model string stored in ``<root>/model.txt``."""

    def __init__(self, root: str | Path) -> None:
        self._path = Path(root) / "model.txt"
        self._lock = threading.Lock()

    async def get(self) -> str | None:
        if not self._path.is_file():
            return None
        try:
            return self._path.read_text(encoding="utf-8").strip() or None
        except Exception as exc:  # noqa: BLE001
            raise ModelConfigStoreUnavailable(
                f"model config read failed ({type(exc).__name__})"
            ) from exc

    async def put(self, model: str) -> str:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = model.strip() + "\n"
        with self._lock:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self._path.parent, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, self._path)
        return model


__all__ = ["FileModelConfigStore"]
