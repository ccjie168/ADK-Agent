"""SLICE-251: the Vue SPA migrates the Runs panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_runs_view_fetches_runs():
    src = _read("src", "views", "RunsView.vue")

    assert "/api/runs" in src
    assert "runs.read" in src


def test_runs_route_uses_runs_view():
    src = _read("src", "router", "index.ts")

    assert "RunsView" in src
    assert 'path: "/runs"' in src


def test_runs_view_renders_fields():
    src = _read("src", "views", "RunsView.vue")

    assert "run_id" in src
    assert "latency_ms" in src
