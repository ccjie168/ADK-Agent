"""Content-addressed agent artifact stores (ADR-0008)."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from ..core import AgentArtifact
from .paths import safe_join

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_HEX = r"^[0-9a-f]{64}$"


class ArtifactStoreError(RuntimeError):
    """An artifact could not be stored or addressed."""


def artifact_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _hexdigest(digest: str) -> str:
    match = _DIGEST.fullmatch(digest)
    if match is None:
        raise ArtifactStoreError("artifact digest must be sha256:<64 hex>")
    return match.group(1)


def _verified_digest(artifact: AgentArtifact, data: bytes) -> str:
    hexdigest = _hexdigest(artifact.digest)
    if len(data) != artifact.size:
        raise ArtifactStoreError("artifact size does not match the data")
    if hashlib.sha256(data).hexdigest() != hexdigest:
        raise ArtifactStoreError("artifact digest does not match the data")
    return hexdigest


class FileArtifactStore:
    """Store artifact bytes under ``<root>/sha256/<hex>``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, hexdigest: str) -> Path:
        directory = safe_join(self.root, "sha256")
        return safe_join(directory, hexdigest, pattern=_HEX)

    async def put(self, artifact: AgentArtifact, data: bytes) -> None:
        hexdigest = _verified_digest(artifact, data)
        target = self._path(hexdigest)
        if target.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{hexdigest}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_bytes(data)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    async def get(self, digest: str) -> bytes | None:
        target = self._path(_hexdigest(digest))
        return target.read_bytes() if target.is_file() else None

    async def has(self, digest: str) -> bool:
        return self._path(_hexdigest(digest)).is_file()


__all__ = ["ArtifactStoreError", "FileArtifactStore", "artifact_digest"]
