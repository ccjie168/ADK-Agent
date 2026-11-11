"""SLICE-007: config-built agents can set a thinking budget."""

from __future__ import annotations

from adk_agent.config import AgentConfig, ModelConfig
from adk_agent.factory import build_agent


def _spec(thinking_budget: int | None = None) -> AgentConfig:
    return AgentConfig(
        name="probe",
        model=ModelConfig(
            provider="gemini",
            name="gemini-2.5-pro",
            thinking_budget=thinking_budget,
        ),
    )


def test_thinking_budget_is_applied():
    agent = build_agent(_spec(0))
    assert agent.generate_content_config.thinking_config.thinking_budget == 0


def test_no_thinking_budget_leaves_generate_content_config_unset():
    agent = build_agent(_spec())
    assert agent.generate_content_config is None
