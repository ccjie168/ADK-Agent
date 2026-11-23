"""SLICE-257: the Vue SPA migrates the Chat panel (SSE streaming)."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_chat_view_fetches_chat():
    src = _read("src", "views", "ChatView.vue")

    assert "/api/chat/stream" in src
    assert "chat.run" in src


def test_chat_route_uses_chat_view():
    src = _read("src", "router", "index.ts")

    assert "ChatView" in src
    assert 'path: "/chat"' in src


def test_chat_view_renders_fields():
    src = _read("src", "views", "ChatView.vue")

    assert "agent" in src
    assert "message" in src
    assert "reply" in src
