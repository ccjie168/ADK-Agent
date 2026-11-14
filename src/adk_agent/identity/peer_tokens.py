"""Static per-peer bearer tokens stored as sha256 hashes (ADR-0014)."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def load_peer_tokens(path: str | Path) -> dict[str, str]:
    """Load ``{peer_id: 64-hex sha256}`` and normalize digests to lowercase."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("peer token file must be a JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("peer token file must be a JSON object")
    tokens: dict[str, str] = {}
    for peer_id, digest in data.items():
        if not isinstance(peer_id, str) or not peer_id:
            raise ValueError("peer token keys must be non-empty strings")
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise ValueError(f"token digest for {peer_id!r} must be 64 hex characters")
        tokens[peer_id] = digest.lower()
    return tokens


def match_peer(tokens: dict[str, str], presented: str) -> str | None:
    """Return the peer id whose stored sha256 matches ``presented``, else ``None``."""
    digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    for peer_id, expected in tokens.items():
        if secrets.compare_digest(digest, expected):
            return peer_id
    return None


__all__ = ["load_peer_tokens", "match_peer"]
