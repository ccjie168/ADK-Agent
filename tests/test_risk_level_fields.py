"""SLICE-168: risk_level on ToolEntry, PlanStep, and ConnectorSpec."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import AgentRef, ConnectorSpec, PlanStep
from adk_agent.tools import ToolEntry


def _entry(**overrides) -> ToolEntry:
    return ToolEntry(tool_id="x", source="function", **overrides)


def _step(**overrides) -> PlanStep:
    return PlanStep(id="a", agent_ref=AgentRef(id="bot", version="1", digest="d" * 64), **overrides)


def _connector(**overrides) -> ConnectorSpec:
    return ConnectorSpec(
        connector_id="crm",
        kind="http",
        base_url="https://crm.example.com",
        methods=["GET"],
        **overrides,
    )


def test_tool_entry_accepts_risk_level():
    assert _entry(risk_level="L3").risk_level == "L3"


def test_plan_step_accepts_risk_level():
    assert _step(risk_level="L2").risk_level == "L2"


def test_connector_spec_accepts_risk_level():
    assert _connector(risk_level="L1").risk_level == "L1"


def test_risk_level_fields_reject_unknown():
    with pytest.raises(ValidationError):
        _entry(risk_level="L5")
    with pytest.raises(ValidationError):
        _step(risk_level="L5")
    with pytest.raises(ValidationError):
        _connector(risk_level="L5")
