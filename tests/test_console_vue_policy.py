"""SLICE-254: the Vue SPA migrates the Policy panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_policy_view_fetches_policy():
    src = _read("src", "views", "PolicyView.vue")

    assert "/api/policy" in src
    assert "policy.read" in src


def test_policy_route_uses_policy_view():
    src = _read("src", "router", "index.ts")

    assert "PolicyView" in src
    assert 'path: "/policy"' in src


def test_policy_view_renders_fields():
    src = _read("src", "views", "PolicyView.vue")

    assert "version" in src
    assert "bindings" in src
