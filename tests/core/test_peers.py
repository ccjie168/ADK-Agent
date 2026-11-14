"""SLICE-090: peer identity and grant model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import PeerGrant, PeerIdentity


def test_peer_identity_defaults():
    peer = PeerIdentity(peer_id="peer-a", tenant="acme", subject="sub-1")

    assert peer.kind == "service"
    assert peer.roles == []
    assert peer.enabled is True


def test_peer_identity_rejects_unsafe_names():
    with pytest.raises(ValidationError):
        PeerIdentity(peer_id="bad id", tenant="acme", subject="sub-1")
    with pytest.raises(ValidationError):
        PeerIdentity(peer_id="peer-a", tenant="bad tenant", subject="sub-1")
    with pytest.raises(ValidationError):
        PeerIdentity(peer_id="peer-a", tenant="acme", subject="")


def test_peer_identity_rejects_invalid_kind():
    with pytest.raises(ValidationError):
        PeerIdentity(peer_id="peer-a", tenant="acme", subject="sub-1", kind="robot")


def test_peer_identity_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PeerIdentity(peer_id="peer-a", tenant="acme", subject="sub-1", extra=1)


def test_peer_identity_frozen():
    peer = PeerIdentity(peer_id="peer-a", tenant="acme", subject="sub-1")

    with pytest.raises(ValidationError):
        peer.enabled = False


def test_peer_grant_valid():
    grant = PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["read"])

    assert grant.actions == ["read"]


def test_peer_grant_rejects_empty_actions():
    with pytest.raises(ValidationError):
        PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=[])


def test_peer_grant_rejects_duplicate_actions():
    with pytest.raises(ValidationError):
        PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["read", "read"])


def test_peer_grant_rejects_unknown_action():
    with pytest.raises(ValidationError):
        PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["run"])


def test_peer_grant_rejects_unsafe_agent_id():
    with pytest.raises(ValidationError):
        PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bad id", actions=["read"])


def test_peer_grant_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["read"], extra=1)
