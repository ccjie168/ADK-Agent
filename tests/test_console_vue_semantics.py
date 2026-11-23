"""SLICE-247: the Vue SPA migrates the Semantics panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_semantics_view_fetches_semantics():
    src = _read("src", "views", "SemanticsView.vue")

    assert "/api/semantics" in src
    assert "ops.read" in src


def test_semantics_route_uses_semantics_view():
    src = _read("src", "router", "index.ts")

    assert "SemanticsView" in src
    assert 'path: "/semantics"' in src


def test_semantics_view_renders_fields():
    src = _read("src", "views", "SemanticsView.vue")

    assert "scheme_id" in src
    assert "concepts" in src
