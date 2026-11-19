"""SLICE-167: RiskLevel type and ToolGrant.risk_level."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import ToolGrant


def test_tool_grant_accepts_risk_level():
    grant = ToolGrant(tool_id="x", risk_level="L3")
    assert grant.risk_level == "L3"


def test_tool_grant_rejects_unknown_risk_level():
    with pytest.raises(ValidationError):
        ToolGrant(tool_id="x", risk_level="L5")


def test_tool_grant_risk_level_defaults_none():
    grant = ToolGrant(tool_id="x")
    assert grant.risk_level is None
