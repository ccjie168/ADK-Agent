"""SLICE-253: the Vue SPA migrates the Plans panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_plans_view_fetches_plans():
    src = _read("src", "views", "PlansView.vue")

    assert "/api/plans" in src
    assert "runs.read" in src


def test_plans_route_uses_plans_view():
    src = _read("src", "router", "index.ts")

    assert "PlansView" in src
    assert 'path: "/plans"' in src


def test_plans_view_renders_fields():
    src = _read("src", "views", "PlansView.vue")

    assert "plan_id" in src
    assert "approvals" in src
