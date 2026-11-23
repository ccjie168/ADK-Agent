"""File-backed tenant-scoped user-to-role bindings for single-host development."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ..core import UserBinding, UserBindingConflict, UserBindingStoreError
from .paths import safe_join

_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def _subject_hash(subject: str) -> str:
    """A path-safe filename for an arbitrary subject string."""
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _read_binding(path: Path) -> UserBinding:
    try:
        return UserBinding.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UserBindingStoreError("user binding store contains an unreadable record") from None


class FileUserBindingStore:
    """One binding per ``(tenant, subject)`` under ``<root>/<tenant>/<sha256(subject)>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _directory(self, tenant: str) -> Path:
        return safe_join(self.root, tenant, pattern=_TENANT.pattern)

    def _path(self, tenant: str, subject: str) -> Path:
        return self._directory(tenant) / f"{_subject_hash(subject)}.json"

    async def add(self, binding: UserBinding) -> UserBinding:
        directory = self._directory(binding.tenant)
        directory.mkdir(parents=True, exist_ok=True)
        path = self._path(binding.tenant, binding.subject)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, binding)
            payload = json.dumps(binding.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=directory, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            try:
                os.link(tmp_path, path)
            except FileExistsError:
                return self._resolve_existing(path, binding)
            finally:
                tmp_path.unlink(missing_ok=True)
        return binding

    async def get(self, tenant: str, subject: str) -> UserBinding | None:
        path = self._path(tenant, subject)
        if not path.is_file():
            return None
        binding = _read_binding(path)
        if binding.tenant != tenant or binding.subject != subject:
            return None
        return binding

    async def list(self, tenant: str) -> list[UserBinding]:
        directory = self._directory(tenant)
        if not directory.is_dir():
            return []
        bindings = [_read_binding(path) for path in directory.glob("*.json")]
        return sorted(
            (binding for binding in bindings if binding.tenant == tenant),
            key=lambda binding: binding.subject,
        )

    async def delete(self, tenant: str, subject: str) -> bool:
        path = self._path(tenant, subject)
        with self._lock:
            if not path.is_file():
                return False
            path.unlink()
            return True

    def _resolve_existing(self, path: Path, binding: UserBinding) -> UserBinding:
        existing = _read_binding(path)
        if existing != binding:
            raise UserBindingConflict(
                f"user binding {binding.tenant}/{binding.subject} already has a different role set"
            )
        return existing


__all__ = ["FileUserBindingStore"]
