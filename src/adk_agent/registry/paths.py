"""Path joining for name-based file stores.

Each component is checked against a whitelist pattern before the joined path is
resolved and confirmed to sit under the store root. Validation alone misses
symlinks planted inside a store, so the containment check is the second line.
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_PART = r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$"


class UnsafePath(ValueError):
    """A path component is unsafe to turn into a filename under a store root."""


def safe_join(root: str | Path, *parts: str, pattern: str = _SAFE_PART) -> Path:
    if not parts:
        raise UnsafePath("safe_join requires at least one path component")
    for part in parts:
        if not isinstance(part, str) or not part or re.fullmatch(pattern, part) is None:
            raise UnsafePath(f"unsafe path component {part!r}")

    candidate = Path(root).joinpath(*parts)
    resolved_root = Path(root).resolve(strict=False)
    if not candidate.resolve(strict=False).is_relative_to(resolved_root):
        raise UnsafePath("path escapes the store root")
    return candidate


__all__ = ["UnsafePath", "safe_join"]
