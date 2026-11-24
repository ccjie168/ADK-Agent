"""SLICE-275: the shell tokens, navigation and capability-ready gate."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_shell_tokens_cover_the_surface_scale():
    tokens = _read("src", "styles", "tokens.css")

    for name in (
        "--canvas",
        "--card",
        "--border",
        "--text",
        "--text-muted",
        "--accent",
        "--accent-soft",
        "--topbar-height",
        "--sidebar-width",
        "--content-max",
        "--space-4",
        "--radius-lg",
    ):
        assert f"{name}:" in tokens


def test_shell_navigation_covers_every_panel():
    app = _read("src", "App.vue")

    for route in (
        "/runs",
        "/plans",
        "/sessions",
        "/approvals",
        "/chat",
        "/ask-ai",
        "/security",
        "/policy",
        "/tools",
        "/grants",
        "/connectors",
        "/credentials",
        "/peers",
        "/semantics",
        "/rag",
        "/quota",
        "/model",
        "/import",
    ):
        assert f'"{route}"' in app
    for group in ("概览", "运行", "治理", "开发", "设置"):
        assert group in app


def test_shell_waits_for_capabilities():
    app = _read("src", "App.vue")
    store = _read("src", "stores", "auth.ts")

    assert "auth.ready" in app
    assert "RouterView v-else" in app
    assert "ready: false" in store
    assert "this.ready = true" in store


def test_shell_shows_the_caller_identity():
    app = _read("src", "App.vue")

    assert "auth.principal?.tenant" in app
    assert "auth.principal?.subject" in app


def test_shell_has_a_mobile_navigation_toggle():
    app = _read("src", "App.vue")
    shell = _read("src", "style.css")

    assert 'aria-label="打开导航"' in app
    assert "navOpen" in app
    assert ".sidebar.open" in shell


def test_shell_styles_use_tokens():
    shell = _read("src", "style.css")
    shell += _read("src", "styles", "tokens.css")

    assert "var(--canvas)" in shell
    assert "var(--accent)" in shell
    assert "#0f766e" not in shell


def test_shell_has_no_raw_html():
    app = _read("src", "App.vue")

    assert "v-html" not in app


def test_shell_has_navigation_icons():
    app = _read("src", "App.vue")
    icon = _read("src", "components", "NavIcon.vue")

    assert "NavIcon" in app
    assert "<svg" in icon
