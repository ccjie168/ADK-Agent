"""SLICE-279: the MCP/A2A ecosystem page."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_ecosystem_route_and_nav():
    router = _read("src", "router", "index.ts")
    shell = _read("src", "App.vue")

    assert "EcosystemView" in router
    assert 'path: "/ecosystem"' in router
    assert 'to="/ecosystem"' in shell


def test_ecosystem_reads_the_three_sources():
    src = _read("src", "views", "EcosystemView.vue")

    assert '"/api/tools"' in src
    assert '"/api/connectors"' in src
    assert '"/api/peers"' in src
    for capability in ("tools.read", "connectors.read", "peers.read"):
        assert capability in src


def test_ecosystem_requires_one_read_capability():
    src = _read("src", "views", "EcosystemView.vue")

    assert "!canTools.value && !canConnectors.value && !canPeers.value" in src


def test_ecosystem_filters_tools_by_source():
    src = _read("src", "views", "EcosystemView.vue")

    for source in ('"mcp"', '"connector"', '"function"', '"openapi"'):
        assert source in src
    assert "filteredTools" in src


def test_ecosystem_ships_onboarding_commands():
    src = _read("src", "views", "EcosystemView.vue")

    assert "connectors register" in src
    assert "--kind mcp" in src
    assert "--transport streamable-http" in src
    assert "peers register" in src


def test_ecosystem_copies_commands():
    src = _read("src", "views", "EcosystemView.vue")

    assert "navigator.clipboard.writeText" in src
    assert "复制命令" in src


def test_ecosystem_uses_empty_states_and_no_raw_html():
    src = _read("src", "views", "EcosystemView.vue")

    assert "EmptyState" in src
    assert "v-html" not in src


def test_ecosystem_shows_dashes_when_a_source_fails():
    src = _read("src", "views", "EcosystemView.vue")

    for ready in ("toolsReady", "connectorsReady", "peersReady"):
        assert ready in src
    assert '"—"' in src
