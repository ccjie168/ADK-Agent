"""SLICE-240: the Vue SPA migrates the Tools catalog panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_tools_view_fetches_tools():
    src = _read("src", "views", "ToolsView.vue")

    assert "/api/tools" in src
    assert "tools.read" in src


def test_tools_route_uses_tools_view():
    src = _read("src", "router", "index.ts")

    assert "ToolsView" in src
    assert 'path: "/tools"' in src


def test_tools_view_renders_columns():
    src = _read("src", "views", "ToolsView.vue")

    assert "tool_id" in src
    assert "granted_agents" in src
