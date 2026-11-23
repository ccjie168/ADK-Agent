"""SLICE-245: the Vue SPA migrates the Quota panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_quota_view_fetches_quota():
    src = _read("src", "views", "QuotaView.vue")

    assert "/api/quota" in src
    assert "ops.read" in src


def test_quota_route_uses_quota_view():
    src = _read("src", "router", "index.ts")

    assert "QuotaView" in src
    assert 'path: "/quota"' in src


def test_quota_view_renders_fields():
    src = _read("src", "views", "QuotaView.vue")

    assert "window_runs" in src
    assert "max_concurrent" in src
