"""SLICE-292: the console has a phone breakpoint that covers every shared layout."""

from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _css() -> str:
    return _WEB.joinpath("src", "style.css").read_text(encoding="utf-8")


def _phone_block() -> str:
    css = _css()
    marker = "@media (max-width: 600px)"
    assert marker in css
    return css.split(marker, 1)[1].split("\n}\n", 1)[0]


def test_phone_breakpoint_covers_the_shell():
    block = _phone_block()
    for selector in (
        ".main",
        ".topbar",
        ".page-head",
        ".row",
        ".form-grid",
        ".metric-grid",
    ):
        assert selector in block, selector


def test_tables_scroll_on_touch():
    block = _phone_block()
    assert "-webkit-overflow-scrolling: touch" in block
    assert ".table-wrap" in block


def test_viewport_allows_safe_areas():
    html = _WEB.joinpath("index.html").read_text(encoding="utf-8")
    match = re.search(r'<meta name="viewport" content="([^"]+)"', html)
    assert match is not None
    assert "viewport-fit=cover" in match.group(1)


def test_chat_composer_clears_the_home_bar():
    view = _WEB.joinpath("src", "views", "ChatView.vue").read_text(encoding="utf-8")
    assert "chat-composer" in view
    block = _phone_block()
    assert ".chat-composer" in block
    composer = block.split(".chat-composer {", 1)[1].split("}", 1)[0]
    assert "env(safe-area-inset-bottom)" in composer


def test_phone_tap_targets():
    block = _phone_block()
    for selector in (".nav-item", ".primary", ".secondary"):
        assert selector in block, selector
    assert "min-height: 40px" in block


def test_login_form_stacks_on_phone():
    block = _phone_block()
    assert ".token-form" in block
    form = block.split(".token-form {", 1)[1].split("}", 1)[0]
    assert "flex-direction: column" in form
    login = block.split(".login {", 1)[1].split("}", 1)[0]
    assert "margin" in login
