"""SLICE-241: the Vue SPA migrates the Grants (tool grants) panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_grants_view_fetches_grants():
    src = _read("src", "views", "GrantsView.vue")

    assert "/api/tool-grants" in src
    assert "grants.read" in src


def test_grants_route_uses_grants_view():
    src = _read("src", "router", "index.ts")

    assert "GrantsView" in src
    assert 'path: "/grants"' in src


def test_grants_view_renders_columns():
    src = _read("src", "views", "GrantsView.vue")

    assert "agent_id" in src
    assert "expires_at" in src
