#!/usr/bin/env python3
"""Set core.hooksPath so git runs the repository hooks."""

from __future__ import annotations

import subprocess  # nosec B404  # runs git config
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ".githooks"


def install(root: str | Path = ROOT) -> int:
    result = subprocess.run(  # nosec B603 B607  # fixed argv, no shell
        ["git", "config", "core.hooksPath", HOOKS],
        cwd=Path(root),
        check=False,
    )
    if result.returncode != 0:
        print("failed to set core.hooksPath", file=sys.stderr)
        return result.returncode
    print(f"core.hooksPath={HOOKS}")
    return 0


def main() -> int:
    return install(ROOT)


if __name__ == "__main__":
    sys.exit(main())
