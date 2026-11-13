"""File-backed lifecycle store. One JSON file per agent version."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..core import AgentLifecycle, LifecycleStatus, transition_lifecycle
from .file import _SAFE_NAME


class FileAgentLifecycleStore:
    """Store lifecycle state under ``<root>/<tenant>/<id>/<version>.lifecycle.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, tenant: str, agent_id: str, version: str) -> Path:
        for value in (tenant, agent_id, version):
            if not _SAFE_NAME.fullmatch(value):
                raise ValueError(f"unsafe lifecycle path component {value!r}")
        return self.root / tenant / agent_id / f"{version}.lifecycle.json"

    async def get(self, tenant: str, agent_id: str, version: str) -> AgentLifecycle:
        path = self._path(tenant, agent_id, version)
        if not path.is_file():
            return AgentLifecycle.default()
        return AgentLifecycle.model_validate_json(path.read_text(encoding="utf-8"))

    async def set(
        self,
        tenant: str,
        agent_id: str,
        version: str,
        *,
        status: LifecycleStatus,
        changed_by: str,
        reason: str,
    ) -> AgentLifecycle:
        current = await self.get(tenant, agent_id, version)
        record = transition_lifecycle(current, status, changed_by=changed_by, reason=reason)
        if record is current:
            return current
        path = self._path(tenant, agent_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = record.model_dump_json(indent=2) + "\n"
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
        return record


__all__ = ["FileAgentLifecycleStore"]
