#!/usr/bin/env python3
"""Require threat-model and evidence sections on active slices, and real test references."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs" / "specs"
TESTS = ROOT / "tests"

REQUIRED = (
    ("## 意图", "intent"),
    ("## 完成判据", "acceptance"),
    ("## 反例", "counterexamples"),
    ("## 5 问威胁建模", "threat-model"),
    ("## 证据", "evidence"),
)
STATUS = re.compile(r"^状态:\s*(\w+)", re.MULTILINE)
TEST_DEF = re.compile(r"^(?:async )?def (test_[A-Za-z0-9_]+)", re.MULTILINE)
TEST_REF = re.compile(r"`(test_[A-Za-z0-9_]+)`")


def missing_sections(text: str) -> list[str]:
    return [label for header, label in REQUIRED if header not in text]


def defined_tests(directory: Path = TESTS) -> set[str]:
    names: set[str] = set()
    for path in directory.rglob("*.py"):
        names.update(TEST_DEF.findall(path.read_text(encoding="utf-8")))
    return names


def check_file(path: Path, known_tests: set[str] | None = None) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = STATUS.search(text)
    if match and match.group(1) == "merged":
        return []
    problems = missing_sections(text)
    if known_tests is not None:
        unknown = sorted(set(TEST_REF.findall(text)) - known_tests)
        problems.extend(f"unknown-test:{name}" for name in unknown)
    return problems


def check_dir(directory: Path, known_tests: set[str] | None = None) -> list[tuple[Path, list[str]]]:
    failures = []
    for path in sorted(directory.glob("SLICE-*.md")):
        problems = check_file(path, known_tests)
        if problems:
            failures.append((path, problems))
    return failures


def main() -> int:
    failures = check_dir(SPECS, defined_tests())
    if failures:
        for path, problems in failures:
            print(f"[FAIL] {path.name}: {', '.join(problems)}")
        return 1
    print(
        "specs: active slices have intent, acceptance, counterexamples, threat-model, "
        "evidence and only real test references"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
