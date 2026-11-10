"""Smoke tests that do not need an API key."""

from __future__ import annotations


def test_package_importable():
    import adk_agent

    assert adk_agent.__version__


def test_normalize_short_strings():
    from adk_agent.models import _normalize

    assert _normalize("gemini:gemini-2.5-pro").provider == "gemini"
    assert _normalize("litellm:deepseek/deepseek-v4-pro").provider == "litellm"
    assert _normalize("deepseek/deepseek-v4-pro").provider == "litellm"


def test_build_gemini_model():
    from adk_agent.models import build_model

    model = build_model("gemini:gemini-2.5-pro")
    assert model.__class__.__name__ == "Gemini"


def test_build_agent_tree():
    from adk_agent.config import AgentConfig
    from adk_agent.factory import build_agent

    cfg = AgentConfig(
        name="tester",
        description="Top-level tester agent.",
        instruction="Say hi.",
        model={"provider": "gemini", "name": "gemini-2.5-pro"},
        sub_agents=[
            {
                "name": "child",
                "description": "Child agent.",
                "instruction": "child",
                "model": {"provider": "gemini", "name": "gemini-2.5-pro"},
            }
        ],
    )
    agent = build_agent(cfg)
    assert agent.name == "tester"
    assert len(agent.sub_agents) == 1
    assert agent.sub_agents[0].name == "child"


def test_disable_thinking():
    from adk_agent import disable_thinking

    config = disable_thinking()
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_budget == 0


def test_build_anthropic_model():
    from adk_agent.models import build_model

    # The plain Anthropic-API adapter, not the Vertex `Claude` subclass.
    model = build_model("claude:deepseek-v4-pro")
    assert type(model).__name__ == "AnthropicLlm"
    assert model.model == "deepseek-v4-pro"


def test_load_config(tmp_path):
    import json

    from adk_agent.config import load_config

    path = tmp_path / "framework.json"
    path.write_text(
        json.dumps(
            {
                "agents": {
                    "a": {
                        "name": "a",
                        "model": {"provider": "gemini", "name": "gemini-2.5-pro"},
                    }
                },
                "expose": "a",
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.agents["a"].name == "a"
    assert cfg.expose == "a"
    assert cfg.transport == "stdio"
