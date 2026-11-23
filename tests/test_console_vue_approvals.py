"""SLICE-242: the Vue SPA migrates the Approvals panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_approvals_view_fetches_approvals():
    src = _read("src", "views", "ApprovalsView.vue")

    assert "/api/approvals" in src
    assert "approvals.read" in src


def test_approvals_route_uses_approvals_view():
    src = _read("src", "router", "index.ts")

    assert "ApprovalsView" in src
    assert 'path: "/approvals"' in src


def test_approvals_view_renders_columns():
    src = _read("src", "views", "ApprovalsView.vue")

    assert "step_id" in src
    assert "expires_at" in src
