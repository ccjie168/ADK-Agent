"""SLICE-264: the Agent hub view aggregates the registry into a journey view."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_agent_hub_fetches_registry():
    src = _read("src", "views", "AgentHubView.vue")

    assert "/api/registry" in src
    assert "registry.read" in src


def test_agent_hub_counts_lifecycle():
    src = _read("src", "views", "AgentHubView.vue")

    assert "published" in src
    assert "deprecated" in src
    assert "retired" in src
    assert "lifecycle" in src


def test_agent_hub_groups_versions():
    src = _read("src", "views", "AgentHubView.vue")

    assert "has_eval_report" in src
    assert "artifact" in src
    assert "groups.get(entry.id)" in src


def test_agents_route_uses_hub():
    router = _read("src", "router", "index.ts")

    assert "AgentHubView" in router
    assert 'path: "/agents", name: "agents", component: AgentHubView' in router
