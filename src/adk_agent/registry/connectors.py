"""File-backed connector registry for single-host development."""

from __future__ import annotations

import builtins
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ..core import ConnectorConflict, ConnectorNotFound, ConnectorSpec
from .paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _definition(spec: ConnectorSpec) -> dict:
    payload = spec.model_dump(mode="json")
    payload.pop("enabled", None)
    return payload


class FileConnectorStore:
    """One immutable definition per connector id under ``<root>/<id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, connector_id: str) -> Path:
        return safe_join(self.root, f"{connector_id}.json", pattern=_NAME.pattern)

    async def add(self, spec: ConnectorSpec) -> ConnectorSpec:
        path = self._path(spec.connector_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, spec)
            payload = json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
                return self._resolve_existing(path, spec)
            finally:
                tmp_path.unlink(missing_ok=True)
        return spec

    async def get(self, connector_id: str) -> ConnectorSpec | None:
        path = self._path(connector_id)
        if not path.is_file():
            return None
        return ConnectorSpec.model_validate_json(path.read_text(encoding="utf-8"))

    async def list(self, tenant: str) -> list[ConnectorSpec]:
        if not self.root.is_dir():
            return []
        specs = []
        for path in self.root.glob("*.json"):
            spec = ConnectorSpec.model_validate_json(path.read_text(encoding="utf-8"))
            if spec.tenant is None or spec.tenant == tenant:
                specs.append(spec)
        return sorted(specs, key=lambda spec: spec.connector_id)

    async def list_all(self) -> builtins.list[ConnectorSpec]:
        if not self.root.is_dir():
            return []
        specs = [
            ConnectorSpec.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.root.glob("*.json")
        ]
        return sorted(specs, key=lambda spec: spec.connector_id)

    async def disable(self, connector_id: str, *, by: str) -> ConnectorSpec:
        path = self._path(connector_id)
        with self._lock:
            if not path.is_file():
                raise ConnectorNotFound(f"connector not found: {connector_id}")
            spec = ConnectorSpec.model_validate_json(path.read_text(encoding="utf-8"))
            if not spec.enabled:
                return spec
            disabled = spec.model_copy(update={"enabled": False})
            payload = json.dumps(disabled.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
            return disabled

    def _resolve_existing(self, path: Path, spec: ConnectorSpec) -> ConnectorSpec:
        existing = ConnectorSpec.model_validate_json(path.read_text(encoding="utf-8"))
        if _definition(existing) != _definition(spec):
            raise ConnectorConflict(
                f"connector {spec.connector_id} already has a different definition"
            )
        return existing


__all__ = ["FileConnectorStore"]
