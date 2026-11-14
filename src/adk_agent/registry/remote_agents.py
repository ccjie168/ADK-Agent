"""File-backed remote A2A agent records and the constrained card fetch (ADR-0015)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from ..core import (
    RemoteAgent,
    RemoteAgentError,
    RemoteAgentFetchError,
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class FileRemoteAgentStore:
    """Store remote agent records under ``<root>/remote-agents/<remote_id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _dir(self) -> Path:
        return self.root / "remote-agents"

    def _path(self, remote_id: str) -> Path:
        if not _SAFE_NAME.fullmatch(remote_id):
            raise ValueError(f"unsafe remote id {remote_id!r}")
        return self._dir() / f"{remote_id}.json"

    async def get(self, remote_id: str) -> RemoteAgent | None:
        path = self._path(remote_id)
        if not path.is_file():
            return None
        return self._load(path)

    async def list(self) -> list[RemoteAgent]:
        if not self._dir().is_dir():
            return []
        records = [self._load(path) for path in self._dir().glob("*.json")]
        records.sort(key=lambda record: record.remote_id)
        return records

    async def put(self, record: RemoteAgent) -> RemoteAgent:
        path = self._path(record.remote_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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

    def _load(self, path: Path) -> RemoteAgent:
        try:
            return RemoteAgent.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RemoteAgentError(f"{path}: invalid remote agent record") from exc


async def fetch_agent_card(
    url: str,
    credential: str | None = None,
    *,
    client: Any = None,
    max_bytes: int = 1_048_576,
) -> tuple[str, dict]:
    import httpx

    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=False)

    try:
        try:
            async with client.stream(
                "GET", url, headers=headers, follow_redirects=False, timeout=5.0
            ) as response:
                if response.status_code in (401, 403):
                    raise RemoteAgentFetchError("unauthorized")
                if response.status_code != 200:
                    raise RemoteAgentFetchError("unreachable")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise RemoteAgentFetchError("too_large")
                    chunks.append(chunk)
        except RemoteAgentFetchError:
            raise
        except httpx.HTTPError:
            raise RemoteAgentFetchError("unreachable") from None
    finally:
        if owns_client:
            await client.aclose()

    raw = b"".join(chunks)
    try:
        card = json.loads(raw)
    except ValueError:
        raise RemoteAgentFetchError("invalid_card") from None
    if not isinstance(card, dict):
        raise RemoteAgentFetchError("invalid_card")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}", card


__all__ = ["FileRemoteAgentStore", "fetch_agent_card"]
