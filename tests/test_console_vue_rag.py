"""SLICE-246: the Vue SPA migrates the RAG panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_rag_view_fetches_rag():
    src = _read("src", "views", "RagView.vue")

    assert "/api/rag" in src
    assert "ops.read" in src


def test_rag_route_uses_rag_view():
    src = _read("src", "router", "index.ts")

    assert "RagView" in src
    assert 'path: "/rag"' in src


def test_rag_view_renders_fields():
    src = _read("src", "views", "RagView.vue")

    assert "recent_retrievals" in src
    assert "last_returned" in src
