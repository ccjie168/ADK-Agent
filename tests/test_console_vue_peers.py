"""SLICE-250: the Vue SPA migrates the Peers panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_peers_view_fetches_peers():
    src = _read("src", "views", "PeersView.vue")

    assert "/api/peers" in src
    assert "peers.read" in src


def test_peers_route_uses_peers_view():
    src = _read("src", "router", "index.ts")

    assert "PeersView" in src
    assert 'path: "/peers"' in src


def test_peers_view_renders_fields():
    src = _read("src", "views", "PeersView.vue")

    assert "peer_id" in src
    assert "grants" in src
