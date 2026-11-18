"""SLICE-146: the slice checklist exists and stays linked from CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = ROOT / "docs" / "guides" / "slice-checklist.md"


def test_slice_checklist_covers_the_required_sections():
    text = CHECKLIST.read_text(encoding="utf-8")

    for heading in (
        "## 顺序",
        "## 已被自动化固化的检查",
        "## 提交前人工检查",
        "## 工具约定",
        "## 停下来问的情况",
    ):
        assert heading in text


def test_claude_md_links_the_checklist():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "docs/guides/slice-checklist.md" in text
