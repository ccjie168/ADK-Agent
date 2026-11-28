#!/usr/bin/env python3
"""Keep ``google.adk`` behind the adapter package (ADR-0046)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "adk_agent"
ALLOWED_PREFIX = "adk_agent.adapters.adk"

# Importers grandfathered by ADR-0046 slices 1 through 3b. Slice 3c moves the
# sandbox and tool-guard modules behind the adapter and empties this list; it
# may never grow.
BASELINE = frozenset(
    {
        "adk_agent.sandbox.agent_channel",
        "adk_agent.sandbox.agent_process",
        "adk_agent.sandbox.agent_worker",
        "adk_agent.sandbox.proxy",
        "adk_agent.sandbox.runner",
        "adk_agent.tools.enforcement",
        "adk_agent.tools.guard",
    }
)


def _module_name(path: Path, root: Path = SOURCE) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = ["adk_agent", *rel.parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_allowed(name: str) -> bool:
    return name == ALLOWED_PREFIX or name.startswith(ALLOWED_PREFIX + ".")


def importers(root: Path = SOURCE) -> dict[str, list[str]]:
    """Map every module outside the adapter that imports ``google.adk``."""
    found: dict[str, list[str]] = {}
    for path in root.rglob("*.py"):
        name = _module_name(path, root)
        if _is_allowed(name):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(
                    alias.name for alias in node.names if alias.name.startswith("google.adk")
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("google.adk"):
                    imported.add(node.module)
                elif node.module == "google" and any(alias.name == "adk" for alias in node.names):
                    imported.add("google.adk")
        if imported:
            found[name] = sorted(imported)
    return found


def violations(root: Path = SOURCE) -> list[str]:
    """Modules that import ``google.adk`` outside the adapter or the baseline."""
    return sorted(name for name in importers(root) if name not in BASELINE)


def main() -> int:
    problems = violations()
    if problems:
        print("google.adk imported outside adk_agent.adapters.adk:", file=__import__("sys").stderr)
        for name in problems:
            print(f"  {name}", file=__import__("sys").stderr)
        return 1
    print(f"[PASS] adk wall: {len(BASELINE)} grandfathered importers, 0 new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
