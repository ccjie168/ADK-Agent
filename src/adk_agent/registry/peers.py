"""File-backed peer identities. One JSON file per peer."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ..core import PeerIdentity, PeerStoreError
from .paths import safe_join

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class FilePeerStore:
    """Store peer identities under ``<root>/peers/<peer_id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _dir(self) -> Path:
        return safe_join(self.root, "peers")

    def _path(self, peer_id: str) -> Path:
        return safe_join(self._dir(), f"{peer_id}.json", pattern=_SAFE_NAME.pattern)

    async def get(self, peer_id: str) -> PeerIdentity | None:
        path = self._path(peer_id)
        if not path.is_file():
            return None
        return self._load(path)

    async def get_by_subject(self, subject: str) -> PeerIdentity | None:
        for record in await self.list():
            if record.subject == subject:
                return record
        return None

    async def list(self) -> list[PeerIdentity]:
        if not self._dir().is_dir():
            return []
        records = [self._load(path) for path in self._dir().glob("*.json")]
        records.sort(key=lambda record: record.peer_id)
        return records

    async def put(self, identity: PeerIdentity) -> PeerIdentity:
        path = self._path(identity.peer_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(identity.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
        return identity

    def _load(self, path: Path) -> PeerIdentity:
        try:
            return PeerIdentity.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise PeerStoreError(f"{path}: invalid peer record") from exc


__all__ = ["FilePeerStore"]
