"""SLICE-093: RemoteAgent domain validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import RemoteAgent, RemoteAgentRegistration, RemoteAgentStatus


def _registration(**overrides) -> dict:
    data = {
        "remote_id": "crm-bot",
        "tenant": "acme",
        "peer_id": "crm",
        "agent_card_url": "https://crm.example.com/.well-known/agent-card.json",
    }
    data.update(overrides)
    return data


def _record(**overrides) -> dict:
    data = {
        "remote_id": "crm-bot",
        "tenant": "acme",
        "peer_id": "crm",
        "agent_card_url": "https://crm.example.com/.well-known/agent-card.json",
        "label": "CRM bot",
        "card_digest": "sha256:" + "a" * 64,
        "checked_at": datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
        "status": "pinned",
    }
    data.update(overrides)
    return data


def test_card_url_rules():
    RemoteAgentRegistration(**_registration())
    RemoteAgentRegistration(**_registration(agent_card_url="http://127.0.0.1:8000/card.json"))
    RemoteAgentRegistration(**_registration(agent_card_url="http://localhost/card.json"))

    for bad in (
        "http://crm.example.com/card.json",
        "https://user@crm.example.com/card.json",
        "ftp://crm.example.com/card.json",
    ):
        with pytest.raises(ValidationError):
            RemoteAgentRegistration(**_registration(agent_card_url=bad))


def test_credential_ref_pattern():
    RemoteAgentRegistration(**_registration(credential_ref="secret://crm/token"))

    for bad in ("crm/token", "secret://", "secret://a b"):
        with pytest.raises(ValidationError):
            RemoteAgentRegistration(**_registration(credential_ref=bad))


def test_digest_pattern():
    RemoteAgent(**_record())
    RemoteAgent(**_record(observed_digest="sha256:" + "b" * 64))

    for bad in ("sha256:abc", "sha256:" + "Z" * 64, "abc"):
        with pytest.raises(ValidationError):
            RemoteAgent(**_record(card_digest=bad))


def test_checked_at_timezone():
    RemoteAgent(**_record())

    with pytest.raises(ValidationError):
        RemoteAgent(**_record(checked_at=datetime(2026, 11, 14, 9, 30)))


def test_status_literal():
    assert set(RemoteAgentStatus.__args__) == {"pinned", "changed", "unreachable"}

    for status in ("pinned", "changed", "unreachable"):
        RemoteAgent(**_record(status=status))

    with pytest.raises(ValidationError):
        RemoteAgent(**_record(status="ok"))
