"""Stable hashes for audit records."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_text(canonical)
