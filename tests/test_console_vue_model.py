"""SLICE-244: the Vue SPA migrates the Model panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_model_view_fetches_model():
    src = _read("src", "views", "ModelView.vue")

    assert "/api/model" in src
    assert "model.read" in src


def test_model_route_uses_model_view():
    src = _read("src", "router", "index.ts")

    assert "ModelView" in src
    assert 'path: "/model"' in src


def test_model_view_renders_fields():
    src = _read("src", "views", "ModelView.vue")

    assert "recent_calls" in src
    assert "fallbacks" in src
