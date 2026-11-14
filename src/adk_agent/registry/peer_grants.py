"""File-backed peer grants. One JSON file per (peer, agent) pair."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ..core import PeerGrant, PeerStoreError

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class FilePeerGrantStore:
    """Store grants under ``<root>/grants/<peer_id>/<agent_id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, peer_id: str, agent_id: str) -> Path:
        if not _SAFE_NAME.fullmatch(peer_id):
            raise ValueError(f"unsafe peer id {peer_id!r}")
        if not _SAFE_NAME.fullmatch(agent_id):
            raise ValueError(f"unsafe agent id {agent_id!r}")
        return self.root / "grants" / peer_id / f"{agent_id}.json"

    async def get(self, peer_id: str, agent_id: str) -> PeerGrant | None:
        path = self._path(peer_id, agent_id)
        if not path.is_file():
            return None
        return self._load(path)

    async def list(self) -> list[PeerGrant]:
        grants_dir = self.root / "grants"
        if not grants_dir.is_dir():
            return []
        records = [self._load(path) for path in grants_dir.glob("*/*.json")]
        records.sort(key=lambda record: (record.peer_id, record.agent_id))
        return records

    async def put(self, grant: PeerGrant) -> PeerGrant:
        path = self._path(grant.peer_id, grant.agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(grant.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
        return grant

    def _load(self, path: Path) -> PeerGrant:
        try:
            return PeerGrant.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise PeerStoreError(f"{path}: invalid peer grant record") from exc


__all__ = ["FilePeerGrantStore"]
