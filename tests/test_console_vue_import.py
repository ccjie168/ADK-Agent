"""SLICE-255: the Vue SPA migrates the Import panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_import_view_fetches_import():
    src = _read("src", "views", "ImportView.vue")

    assert "/api/import" in src
    assert "runs.read" in src


def test_import_route_uses_import_view():
    src = _read("src", "router", "index.ts")

    assert "ImportView" in src
    assert 'path: "/import"' in src


def test_import_view_renders_fields():
    src = _read("src", "views", "ImportView.vue")

    assert "terminology" in src
    assert "agent" in src
