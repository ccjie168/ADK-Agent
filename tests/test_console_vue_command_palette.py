"""SLICE-307: the Vue console has a capability-aware command palette."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WEB = _ROOT / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def _nav_routes() -> list[str]:
    return re.findall(r'to:\s*"(/[^"]*)"', _read("src", "nav.ts"))


def test_nav_source_is_shared():
    nav = _read("src", "nav.ts")
    app = _read("src", "App.vue")
    router = _read("src", "router", "index.ts")
    capabilities = _read("src", "api", "capabilities.ts")

    assert "NAV_GROUPS" in nav
    assert "CommandPalette" in app

    routes = set(_nav_routes())
    assert len(routes) >= 26
    for route in routes:
        if route == "/guide":
            assert "external: true" in nav
            continue
        assert f'path: "{route}"' in router, route
    for capability in re.findall(r'"([a-z]+\.[a-z]+)"', nav):
        assert f'"{capability}"' in capabilities, capability

    sidebar = set(re.findall(r'to="(/[^"]*)"', app.split("<template>", 1)[1]))
    assert sidebar == routes - {"/guide"}


def test_palette_filters_by_capability():
    palette = _read("src", "components", "CommandPalette.vue")

    assert "NAV_GROUPS" in palette
    assert "capabilities" in palette
    assert "hasCapability" in palette
    assert "external" in palette
    assert "v-html" not in palette
    assert "toLowerCase" in palette


def test_palette_keyboard_and_a11y():
    palette = _read("src", "components", "CommandPalette.vue")

    assert 'role="dialog"' in palette
    assert 'aria-modal="true"' in palette
    assert "aria-label" in palette
    assert "aria-activedescendant" in palette
    assert "ArrowDown" in palette
    assert "ArrowUp" in palette
    assert "Enter" in palette
    assert "Escape" in palette
    assert "nextTick" in palette
    assert "focus()" in palette
    assert "returnFocus" in palette
    assert "activeElement" in palette
    assert '"Tab"' in palette


def test_palette_shortcut_is_wired():
    app = _read("src", "App.vue")

    assert "CommandPalette" in app
    assert "paletteOpen" in app
    assert "ctrlKey" in app and "metaKey" in app
    assert '"k"' in app or "'k'" in app
    assert 'addEventListener("keydown"' in app
    assert 'removeEventListener("keydown"' in app


def test_palette_is_built():
    assets = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (_WEB / "dist" / "assets").glob("*.js")
    )

    assert "命令面板" in assets
    assert "跳转到页面" in assets


def test_guide_documents_the_palette():
    guide = (_ROOT / "docs" / "guides" / "console-ui.html").read_text(encoding="utf-8")

    assert "命令面板" in guide
    assert "Ctrl" in guide
    assert "⌘" in guide
    assert "Esc" in guide
