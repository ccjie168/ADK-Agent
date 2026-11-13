"""SLICE-078: tool grant requests and their expiry semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import ToolGrantRequest, effective_status

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _request(**overrides):
    data = {
        "request_id": "r1",
        "tenant": "acme",
        "agent_id": "bot",
        "version": "1.0.0",
        "digest": "sha256:" + "a" * 64,
        "tool_id": "crm.read",
        "data_classes": ["internal"],
        "reason": "support needs it",
        "status": "pending",
        "requested_by": "alice",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=2),
    }
    data.update(overrides)
    return ToolGrantRequest(**data)


def test_request_validation():
    with pytest.raises(ValidationError):
        _request(requested_at=datetime(2026, 11, 14, 12, 0))
    with pytest.raises(ValidationError):
        _request(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        _request(digest="")


def test_effective_status():
    assert effective_status(_request(), NOW) == "pending"
    assert effective_status(_request(), NOW + timedelta(hours=3)) == "expired"

    approved = _request(
        status="approved",
        decided_by="bob",
        decided_at=NOW,
        decision_reason="ok",
    )
    assert effective_status(approved, NOW + timedelta(hours=1)) == "approved"
    assert effective_status(approved, NOW + timedelta(hours=3)) == "expired"

    denied = _request(status="denied", decided_by="bob", decided_at=NOW)
    assert effective_status(denied, NOW + timedelta(days=30)) == "denied"
