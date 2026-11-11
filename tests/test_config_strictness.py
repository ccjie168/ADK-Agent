"""SLICE-010: config rejects typos and bad references at parse time."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.config import AgentConfig, FrameworkConfig, McpServerConfig, ModelConfig


def test_model_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ModelConfig(provider="gemini", name="gemini-2.5-pro", thinking_buget=0)


def test_mcp_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        McpServerConfig(transport="stdio", command="npx", tramsport="http")


def test_agent_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        AgentConfig(name="probe", instruciton="typo")


def test_framework_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        FrameworkConfig(agents={}, expse="probe")


def test_expose_must_exist():
    with pytest.raises(ValidationError):
        FrameworkConfig(agents={}, expose="missing")


def test_valid_config_still_loads():
    cfg = FrameworkConfig(agents={"probe": AgentConfig(name="probe")}, expose="probe")
    assert cfg.expose == "probe"
    assert cfg.transport == "stdio"
