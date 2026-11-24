"""SLICE-275: the shell tokens, navigation and capability-ready gate."""

from __future__ import annotations

import re
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
        "/",
        "/agents",
        "/registry",
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
        "/ecosystem",
        "/import",
        "/audit",
        "/roles",
        "/users",
        "/settings",
    ):
        assert f'"{route}"' in app
    for group in ("概览", "运行", "治理", "开发", "设置"):
        assert group in app


def test_shell_waits_for_capabilities():
    app = _read("src", "App.vue")
    store = _read("src", "stores", "auth.ts")

    assert "auth.resolved" in app
    assert "RouterView" in app
    assert "resolved: false" in store
    assert "this.resolved = true" in store


def test_auth_store_holds_the_shell_for_every_login_path():
    store = _read("src", "stores", "auth.ts")
    login = store[store.index("setTokenFromInput") : store.index("async startLogin")]
    callback = store[store.index("async finishLogin") : store.index("logout()")]
    initial = store[store.index("async init") : store.index("setTokenFromInput")]

    for path in (login, callback, initial):
        assert path.index("resolved = false") < path.index("fetchMe")
        assert "resolved = true" in path
    assert "finally" in initial


def test_auth_store_clears_a_rejected_token():
    store = _read("src", "stores", "auth.ts")

    assert "response.status === 401" in store
    assert "clearToken()" in store
    assert "meError" in store


def test_shell_shows_the_caller_identity():
    app = _read("src", "App.vue")

    assert "auth.principal?.tenant" in app
    assert "auth.principal?.subject" in app


def test_shell_has_a_mobile_navigation_toggle():
    app = _read("src", "App.vue")
    shell = _read("src", "style.css")

    assert "打开导航" in app
    assert "aria-expanded" in app
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


def _token(tokens: str, name: str) -> str:
    match = re.search(rf"{name}:\s*(#[0-9a-fA-F]{{6}})", tokens)
    assert match is not None, name
    return match.group(1)


def _contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_tokens_meet_text_contrast():
    tokens = _read("src", "styles", "tokens.css")

    pairs = (
        ("--text", "--card"),
        ("--text-muted", "--canvas"),
        ("--text-subtle", "--sidebar"),
        ("--accent", "--card"),
    )
    for foreground, background in pairs:
        assert _contrast(_token(tokens, foreground), _token(tokens, background)) >= 4.5
