"""SLICE-270: the peers panel registers peers and remote catalog entries."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_peers_view_registers_peer():
    src = _read("src", "views", "PeersView.vue")

    assert '"/api/peers"' in src
    assert "peers.manage" in src
    assert "peer_id" in src


def test_peers_view_disables_peer():
    src = _read("src", "views", "PeersView.vue")

    assert "/disable" in src


def test_peers_view_registers_remote_agent():
    src = _read("src", "views", "PeersView.vue")

    assert "/api/remote-agents" in src
    assert "agent_card_url" in src
    assert "credential_ref" in src
