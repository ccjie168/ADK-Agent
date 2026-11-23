"""SLICE-256: the Vue SPA migrates the Ask AI panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_ask_ai_view_fetches_ask_ai():
    src = _read("src", "views", "AskAiView.vue")

    assert "/api/ask-ai" in src
    assert "runs.read" in src


def test_ask_ai_route_uses_ask_ai_view():
    src = _read("src", "router", "index.ts")

    assert "AskAiView" in src
    assert 'path: "/ask-ai"' in src


def test_ask_ai_view_renders_fields():
    src = _read("src", "views", "AskAiView.vue")

    assert "text" in src
    assert "bindings" in src
