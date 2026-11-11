#!/usr/bin/env python3
"""Single gate entry. Usage: python scripts/check.py [--fast|--full] [--strict]

Exit code 0 = ALL PASS, 1 = FAILED.
Missing tools are SKIP by default; with --strict they become FAIL.
Output is ASCII only (Windows console safety).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess  # nosec B404  # runs the gate tools
import sys
from pathlib import Path

PY = sys.executable
ROOT = Path(__file__).resolve().parents[1]

FAST_STEPS: list[tuple[str, str | None, list[str]]] = [
    ("format", "ruff", ["-m", "ruff", "format", "--check", "."]),
    ("lint", "ruff", ["-m", "ruff", "check", "--no-cache", "."]),
    ("types", "mypy", ["-m", "mypy", "src"]),
    ("layering", "importlinter", ["scripts/check_layering.py"]),
    ("specs", None, ["scripts/check_specs.py"]),
    ("test", "pytest", ["-m", "pytest", "-q"]),
]

FULL_STEPS: list[tuple[str, str | None, list[str]]] = FAST_STEPS + [
    ("sast", "bandit", ["-m", "bandit", "-q", "-r", "src", "scripts"]),
    ("deps", "pip_audit", ["-m", "pip_audit"]),
]

# detect-secrets has no exit-code signal; we parse its JSON and count hits.
SECRET_EXCLUDES = (
    r"(^|[\\/])(\.venv|\.git|\.mypy_cache|\.ruff_cache|__pycache__|"  # nosec B105  # path regex
    r"\.pytest_cache|\.import_linter_cache|node_modules|docs[\\/]evidence)([\\/]|$)"
)


def _available(module: str | None) -> bool:
    return module is None or importlib.util.find_spec(module) is not None


def _run(name: str, args: list[str]) -> bool:
    proc = subprocess.run([PY, *args], cwd=ROOT)  # nosec B603  # fixed argv, no shell
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def _run_secrets() -> bool | None:
    if not _available("detect_secrets"):
        print("[SKIP] secrets: detect_secrets not found")
        return None
    cmd = [
        PY,
        "-m",
        "detect_secrets",
        "scan",
        "--all-files",
        "--force-use-all-plugins",
        "--exclude-files",
        SECRET_EXCLUDES,
        ".",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)  # nosec B603  # fixed argv
    if proc.returncode != 0:
        print(proc.stderr.strip())
        print("[FAIL] secrets")
        return False
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        print("[FAIL] secrets: unparsable detect-secrets output")
        return False
    results = data.get("results", {})
    count = sum(len(hits) for hits in results.values())
    if count:
        for path, hits in results.items():
            print(f"  {path}: {len(hits)}")
        print(f"[FAIL] secrets: {count} potential secret(s)")
        return False
    print("[PASS] secrets")
    return True


def select_steps(argv: list[str]) -> list:
    """Return the steps for the requested gate. ``--full`` is cumulative."""
    return FULL_STEPS if "--full" in argv else FAST_STEPS


def main() -> int:
    steps = select_steps(sys.argv)
    strict = "--strict" in sys.argv

    results: list[bool | None] = []
    for name, module, args in steps:
        if not _available(module):
            print(f"[SKIP] {name}: {module} not found")
            results.append(None)
            continue
        results.append(_run(name, args))

    results.append(_run_secrets())

    failed = sum(1 for r in results if r is False)
    skipped = sum(1 for r in results if r is None)
    if strict and skipped:
        failed += skipped
        print(f"[FAIL] {skipped} skipped step(s) under --strict")

    total = len(results)
    print("ALL PASS" if failed == 0 else f"FAILED ({failed} failed / {total} steps)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
