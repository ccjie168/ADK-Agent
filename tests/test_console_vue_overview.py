"""SLICE-238: the Vue SPA migrates the Overview panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_overview_view_fetches_overview():
    src = _read("src", "views", "OverviewView.vue")

    assert "/api/overview" in src
    assert "ops.read" in src


def test_home_route_uses_overview_view():
    src = _read("src", "router", "index.ts")

    assert "OverviewView" in src
    assert 'path: "/"' in src


def test_router_has_panel_routes():
    src = _read("src", "router", "index.ts")

    assert 'path: "/approvals"' in src
    assert 'path: "/grants"' in src
