"""File-backed registry. One immutable JSON file per agent version."""

from __future__ import annotations

import builtins
import json
import os
import re
import tempfile
from pathlib import Path

from ..core import AgentRef, PublishedAgent, manifest_digest
from .paths import safe_join

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class RegistryError(Exception):
    """Base class for registry failures."""


class RegistryConflict(RegistryError):
    """The same agent version was published with different content."""


class RegistryIntegrityError(RegistryError):
    """A stored record does not match its digest."""


class FileAgentRegistry:
    """Store published agents under ``<root>/<tenant>/<id>/<version>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, tenant: str, agent_id: str, version: str) -> Path:
        return safe_join(self.root, tenant, agent_id, f"{version}.json", pattern=_SAFE_NAME.pattern)

    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None:
        path = self._path(tenant, ref.id, ref.version)
        if not path.is_file():
            return None
        published = self._load(path)
        if (
            published.manifest.tenant != tenant
            or published.manifest.id != ref.id
            or published.manifest.version != ref.version
            or published.digest != ref.digest
        ):
            return None
        return published

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]:
        tenant_dir = safe_join(self.root, tenant, pattern=_SAFE_NAME.pattern)
        if not tenant_dir.is_dir():
            return []

        records: builtins.list[PublishedAgent] = []
        for agent_dir in tenant_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            for path in agent_dir.glob("*.json"):
                if path.name.endswith((".eval.json", ".lifecycle.json")):
                    continue
                records.append(self._load(path))
        records.sort(key=lambda record: (record.manifest.id, record.manifest.version))
        return records

    async def tenants(self) -> builtins.list[str]:
        if not self.root.is_dir():
            return []
        names = [
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and _SAFE_NAME.fullmatch(entry.name)
        ]
        return sorted(names)

    async def publish(self, agent: PublishedAgent) -> PublishedAgent:
        path = self._path(agent.manifest.tenant, agent.manifest.id, agent.manifest.version)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return self._resolve_existing(path, agent)

        payload = json.dumps(agent.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
            return self._resolve_existing(path, agent)
        finally:
            tmp_path.unlink(missing_ok=True)
        return agent

    def _load(self, path: Path) -> PublishedAgent:
        try:
            published = PublishedAgent.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RegistryIntegrityError(f"{path}: invalid published agent record") from exc
        if manifest_digest(published.manifest) != published.digest:
            raise RegistryIntegrityError(f"{path}: digest does not match its manifest")
        return published

    def _resolve_existing(self, path: Path, agent: PublishedAgent) -> PublishedAgent:
        existing = self._load(path)
        if existing.digest != agent.digest:
            raise RegistryConflict(
                f"{agent.manifest.tenant}/{agent.manifest.id}@{agent.manifest.version} "
                f"already published with digest {existing.digest}"
            )
        return existing
