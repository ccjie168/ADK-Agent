"""File-backed registry. One immutable JSON file per agent version."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..core import AgentRef, PublishedAgent, manifest_digest


class RegistryError(Exception):
    """Base class for registry failures."""


class RegistryConflict(RegistryError):
    """The same agent version was published with different content."""


class RegistryIntegrityError(RegistryError):
    """A stored record does not match its digest."""


class FileAgentRegistry:
    """Store published agents under ``<root>/<id>/<version>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, agent_id: str, version: str) -> Path:
        return self.root / agent_id / f"{version}.json"

    async def get(self, ref: AgentRef) -> PublishedAgent | None:
        path = self._path(ref.id, ref.version)
        if not path.is_file():
            return None
        published = self._load(path)
        if (
            published.manifest.id != ref.id
            or published.manifest.version != ref.version
            or published.digest != ref.digest
        ):
            return None
        return published

    async def publish(self, agent: PublishedAgent) -> PublishedAgent:
        path = self._path(agent.manifest.id, agent.manifest.version)
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
        published = PublishedAgent.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest_digest(published.manifest) != published.digest:
            raise RegistryIntegrityError(f"{path}: digest does not match its manifest")
        return published

    def _resolve_existing(self, path: Path, agent: PublishedAgent) -> PublishedAgent:
        existing = self._load(path)
        if existing.digest != agent.digest:
            raise RegistryConflict(
                f"{agent.manifest.id}@{agent.manifest.version} already published "
                f"with digest {existing.digest}"
            )
        return existing
