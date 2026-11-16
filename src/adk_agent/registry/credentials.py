"""File-backed tenant credential bindings for single-host development."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ..core import (
    ConnectorSpec,
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    CredentialStore,
    parse_credential_ref,
)

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _definition(binding: CredentialBinding) -> dict:
    payload = binding.model_dump(mode="json")
    payload.pop("enabled", None)
    return payload


class FileCredentialStore:
    """One binding per ``(tenant, credential_id)`` under ``<root>/<tenant>/<id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, tenant: str, credential_id: str) -> Path:
        if not _NAME.fullmatch(tenant):
            raise ValueError(f"unsafe tenant {tenant!r}")
        if not _NAME.fullmatch(credential_id):
            raise ValueError(f"unsafe credential id {credential_id!r}")
        return self.root / tenant / f"{credential_id}.json"

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

    async def get(self, tenant: str, credential_id: str) -> CredentialBinding | None:
        path = self._path(tenant, credential_id)
        if not path.is_file():
            return None
        return CredentialBinding.model_validate_json(path.read_text(encoding="utf-8"))

    async def list(self, tenant: str) -> list[CredentialBinding]:
        if not _NAME.fullmatch(tenant):
            raise ValueError(f"unsafe tenant {tenant!r}")
        directory = self.root / tenant
        if not directory.is_dir():
            return []
        bindings = [
            CredentialBinding.model_validate_json(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.json")
        ]
        return sorted(
            (binding for binding in bindings if binding.tenant == tenant),
            key=lambda binding: binding.credential_id,
        )

    async def disable(self, tenant: str, credential_id: str, *, by: str) -> CredentialBinding:
        path = self._path(tenant, credential_id)
        with self._lock:
            if not path.is_file():
                raise CredentialNotFound(f"credential not found: {tenant}/{credential_id}")
            binding = CredentialBinding.model_validate_json(path.read_text(encoding="utf-8"))
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
        existing = CredentialBinding.model_validate_json(path.read_text(encoding="utf-8"))
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
