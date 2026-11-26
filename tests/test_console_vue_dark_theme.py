"""SLICE-302: the Vue console ships a persisted dark theme."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WEB = _ROOT / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_dark_tokens_override_colors():
    tokens = _read("src", "styles", "tokens.css")
    assert '[data-theme="dark"]' in tokens
    dark = tokens.split('[data-theme="dark"]', 1)[1].split("}", 1)[0]
    assert "color-scheme: dark" in dark
    for name in ("--canvas", "--card", "--text", "--border", "--accent"):
        assert name in dark


def test_app_toggles_and_persists_theme():
    app = _read("src", "App.vue")
    assert "adk_theme" in app
    assert "data-theme" in app
    assert "aria-pressed" in app
    assert "toggleTheme" in app


def test_index_applies_theme_before_mount():
    index = _read("index.html")
    assert "adk_theme" in index
    assert "prefers-color-scheme" in index
    assert index.index("data-theme") < index.index('id="app"')


def test_styles_use_tokens_only():
    style = _read("src", "style.css")
    assert re.search(r"#[0-9a-fA-F]{6}", style) is None


def test_dark_theme_is_built():
    assets = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (_WEB / "dist" / "assets").glob("*.js")
    )
    assert "adk_theme" in assets
    assert "data-theme" in assets


def test_guide_documents_dark_theme():
    guide = (_ROOT / "docs" / "guides" / "console-ui.html").read_text(encoding="utf-8")
    assert "深色" in guide
    assert "主题" in guide
