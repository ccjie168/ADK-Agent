"""SLICE-213: guides state the tenant a token-only console uses."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _guide(name: str) -> str:
    return (ROOT / "docs" / "guides" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["install-and-use.md", "operations.md"])
def test_guides_state_the_token_only_tenant(name):
    text = _guide(name)

    assert "租户固定为 `local`" in text
    assert "console_user" in text
    assert "tenant_claim" in text


def test_install_guide_marks_oidc_as_the_production_path():
    text = _guide("install-and-use.md")
    platform = text.index("租户固定为 `local`")
    production = text.index("正式部署用 OIDC", platform)

    assert production > platform
