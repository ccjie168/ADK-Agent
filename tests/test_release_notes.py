"""SLICE-145: the release notes match the project version and cover the release."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^\[project\][\s\S]*?^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_release_notes_exist_for_the_project_version():
    assert (ROOT / "docs" / "releases" / f"v{_version()}.md").is_file()


def test_release_notes_cover_the_required_sections():
    notes = (ROOT / "docs" / "releases" / f"v{_version()}.md").read_text(encoding="utf-8")

    for heading in ("包含内容", "安装", "升级说明", "已知缺口", "发布验证"):
        assert re.search(rf"^## {re.escape(heading)}$", notes, re.MULTILINE), heading


def test_release_notes_have_no_unfilled_placeholders():
    notes = (ROOT / "docs" / "releases" / f"v{_version()}.md").read_text(encoding="utf-8")

    assert not re.search("TODO|TBD", notes, re.IGNORECASE)
