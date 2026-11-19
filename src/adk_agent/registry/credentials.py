"""File-backed tenant credential bindings for single-host development."""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ..core import (
    ConnectorSpec,
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    CredentialStore,
    CredentialStoreError,
    parse_credential_ref,
)
from .paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def _read_binding(path: Path) -> CredentialBinding:
    try:
        return CredentialBinding.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CredentialStoreError("credential store contains an unreadable record") from None


def _acquire_lock(
    fd: int,
    lock: Callable[[int], None],
    *,
    attempts: int = 100,
    delay: float = 0.05,
) -> None:
    for attempt in range(attempts):
        try:
            lock(fd)
            return
        except OSError:
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise CredentialStoreError("credential store lock unavailable")


def _definition(binding: CredentialBinding) -> dict:
    payload = binding.model_dump(mode="json")
    payload.pop("enabled", None)
    return payload


@contextmanager
def _store_lock(path: Path) -> Iterator[None]:
    """Serialise writers across processes with an OS-level lock on a sibling file."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            msvcrt = importlib.import_module("msvcrt")

            def _lock_windows(handle: int) -> None:
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)

            _acquire_lock(fd, _lock_windows)
        else:
            fcntl = importlib.import_module("fcntl")
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            if os.name == "nt":
                msvcrt = importlib.import_module("msvcrt")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class FileCredentialStore:
    """One binding per ``(tenant, credential_id)`` under ``<root>/<tenant>/<id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, tenant: str, credential_id: str) -> Path:
        base = safe_join(self.root, tenant, credential_id, pattern=_NAME.pattern)
        return base.with_name(f"{base.name}.json")

    async def add(self, binding: CredentialBinding) -> CredentialBinding:
        path = self._path(binding.tenant, binding.credential_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, binding)
            payload = json.dumps(binding.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
                return self._resolve_existing(path, binding)
            finally:
                tmp_path.unlink(missing_ok=True)
        return binding

    async def replace_wrapped(
        self,
        tenant: str,
        credential_id: str,
        wrapped_secret: dict,
        secret_key_id: str,
    ) -> CredentialBinding:
        path = self._path(tenant, credential_id)
        with self._lock, _store_lock(path):
            if not path.is_file():
                raise CredentialNotFound(f"credential not found: {tenant}/{credential_id}")
            existing = _read_binding(path)
            updated = existing.model_copy(
                update={"wrapped_secret": wrapped_secret, "secret_key_id": secret_key_id}
            )
            payload = json.dumps(updated.model_dump(mode="json"), indent=2, sort_keys=True) + chr(
                10
            )
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
        return updated

    async def get(self, tenant: str, credential_id: str) -> CredentialBinding | None:
        path = self._path(tenant, credential_id)
        if not path.is_file():
            return None
        return _read_binding(path)

    async def list(self, tenant: str) -> list[CredentialBinding]:
        directory = safe_join(self.root, tenant, pattern=_NAME.pattern)
        if not directory.is_dir():
            return []
        bindings = [_read_binding(path) for path in directory.glob("*.json")]
        return sorted(
            (binding for binding in bindings if binding.tenant == tenant),
            key=lambda binding: binding.credential_id,
        )

    async def disable(self, tenant: str, credential_id: str, *, by: str) -> CredentialBinding:
        path = self._path(tenant, credential_id)
        with self._lock, _store_lock(path):
            if not path.is_file():
                raise CredentialNotFound(f"credential not found: {tenant}/{credential_id}")
            binding = _read_binding(path)
            if not binding.enabled:
                return binding
            disabled = binding.model_copy(update={"enabled": False})
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

    def _resolve_existing(self, path: Path, binding: CredentialBinding) -> CredentialBinding:
        existing = _read_binding(path)
        if _definition(existing) != _definition(binding):
            raise CredentialConflict(
                f"credential {binding.tenant}/{binding.credential_id} "
                "already has a different definition"
            )
        return existing


async def credential_is_bound(store: CredentialStore | None, spec: ConnectorSpec) -> bool:
    """Whether a connector's ``auth_ref`` resolves to an enabled binding.

    Single-segment references are global and carry no tenant binding, so they
    are always considered bound.
    """
    if store is None or spec.auth_ref is None:
        return True
    try:
        ref_tenant, _ = parse_credential_ref(spec.auth_ref)
    except ValueError:
        return True
    if spec.tenant is None or spec.tenant != ref_tenant:
        return False
    bindings = await store.list(spec.tenant)
    return any(binding.enabled and binding.secret_ref == spec.auth_ref for binding in bindings)


__all__ = ["FileCredentialStore", "credential_is_bound"]
