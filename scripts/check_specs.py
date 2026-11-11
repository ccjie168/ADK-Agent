#!/usr/bin/env python3
"""Require threat-model and evidence sections on active slices."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs" / "specs"

REQUIRED = (
    ("## 意图", "intent"),
    ("## 完成判据", "acceptance"),
    ("## 反例", "counterexamples"),
    ("## 5 问威胁建模", "threat-model"),
    ("## 证据", "evidence"),
)
STATUS = re.compile(r"^状态:\s*(\w+)", re.MULTILINE)


def missing_sections(text: str) -> list[str]:
    return [label for header, label in REQUIRED if header not in text]


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = STATUS.search(text)
    if match and match.group(1) == "merged":
        return []
    return missing_sections(text)


def check_dir(directory: Path) -> list[tuple[Path, list[str]]]:
    failures = []
    for path in sorted(directory.glob("SLICE-*.md")):
        missing = check_file(path)
        if missing:
            failures.append((path, missing))
    return failures


def main() -> int:
    failures = check_dir(SPECS)
    if failures:
        for path, missing in failures:
            print(f"[FAIL] {path.name}: missing {', '.join(missing)}")
        return 1
    print("specs: active slices have intent, acceptance, counterexamples, threat-model, evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
