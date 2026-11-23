"""SLICE-252: the Vue SPA migrates the Sessions panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_sessions_view_fetches_sessions():
    src = _read("src", "views", "SessionsView.vue")

    assert "/api/sessions" in src
    assert "sessions.read" in src


def test_sessions_route_uses_sessions_view():
    src = _read("src", "router", "index.ts")

    assert "SessionsView" in src
    assert 'path: "/sessions"' in src


def test_sessions_view_renders_fields():
    src = _read("src", "views", "SessionsView.vue")

    assert "session_id" in src
    assert "last_update_time" in src
