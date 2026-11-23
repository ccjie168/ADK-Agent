"""SLICE-248: the Vue SPA migrates the Connectors panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_connectors_view_fetches_connectors():
    src = _read("src", "views", "ConnectorsView.vue")

    assert "/api/connectors" in src
    assert "connectors.read" in src


def test_connectors_route_uses_connectors_view():
    src = _read("src", "router", "index.ts")

    assert "ConnectorsView" in src
    assert 'path: "/connectors"' in src


def test_connectors_view_renders_fields():
    src = _read("src", "views", "ConnectorsView.vue")

    assert "connector_id" in src
    assert "base_url" in src
