"""File-backed global role definitions for single-host development."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ..core import RoleConflict, RoleDefinition, RoleStoreError
from .paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def _read_role(path: Path) -> RoleDefinition:
    try:
        return RoleDefinition.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RoleStoreError("role store contains an unreadable record") from None


class FileRoleStore:
    """One role per ``<name>.json`` directly under ``root`` (global, no tenant)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        base = safe_join(self.root, name, pattern=_NAME.pattern)
        return base.with_name(f"{base.name}.json")

    async def add(self, role: RoleDefinition) -> RoleDefinition:
        path = self._path(role.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, role)
            payload = json.dumps(role.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
                return self._resolve_existing(path, role)
            finally:
                tmp_path.unlink(missing_ok=True)
        return role

    async def get(self, name: str) -> RoleDefinition | None:
        path = self._path(name)
        if not path.is_file():
            return None
        return _read_role(path)

    async def list(self) -> list[RoleDefinition]:
        if not self.root.is_dir():
            return []
        roles = [_read_role(path) for path in self.root.glob("*.json")]
        return sorted(roles, key=lambda role: role.name)

    async def delete(self, name: str) -> bool:
        path = self._path(name)
        with self._lock:
            if not path.is_file():
                return False
            path.unlink()
            return True

    def _resolve_existing(self, path: Path, role: RoleDefinition) -> RoleDefinition:
        existing = _read_role(path)
        if existing != role:
            raise RoleConflict(f"role {role.name!r} already has a different definition")
        return existing


__all__ = ["FileRoleStore"]
