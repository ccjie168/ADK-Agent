"""File-backed terminology (concept schemes) for single-host development."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ..semantics import ConceptScheme
from ..semantics.store import ConceptSchemeStoreUnavailable
from .paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class FileConceptSchemeStore:
    """One scheme per ``(tenant, scheme_id)`` under ``<root>/<tenant>/<scheme_id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, tenant: str, scheme_id: str) -> Path:
        return safe_join(self.root, tenant, f"{scheme_id}.json", pattern=_NAME.pattern)

    async def put(self, tenant: str, scheme: ConceptScheme) -> ConceptScheme:
        path = self._path(tenant, scheme.scheme_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(scheme.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        with self._lock:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
        return scheme

    async def get(self, tenant: str, scheme_id: str) -> ConceptScheme | None:
        path = self._path(tenant, scheme_id)
        if not path.is_file():
            return None
        return self._read(path)

    async def list(self, tenant: str) -> list[ConceptScheme]:
        directory = safe_join(self.root, tenant, pattern=_NAME.pattern)
        if not directory.is_dir():
            return []
        return [self._read(path) for path in sorted(directory.glob("*.json"))]

    @staticmethod
    def _read(path: Path) -> ConceptScheme:
        try:
            return ConceptScheme.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ConceptSchemeStoreUnavailable(
                f"terminology read failed ({type(exc).__name__})"
            ) from exc


__all__ = ["FileConceptSchemeStore"]
