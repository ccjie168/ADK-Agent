"""SLICE-011: building a model must not mutate the process environment."""

from __future__ import annotations

import os

from adk_agent.config import ModelConfig
from adk_agent.models import build_model


def test_gemini_key_does_not_mutate_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    cfg = ModelConfig(
        provider="gemini",
        name="gemini-2.5-pro",
        api_key="secret",  # pragma: allowlist secret
    )
    build_model(cfg)
    assert "GOOGLE_API_KEY" not in os.environ


def test_gemini_key_does_not_override_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "existing")
    cfg = ModelConfig(
        provider="gemini",
        name="gemini-2.5-pro",
        api_key="secret",  # pragma: allowlist secret
    )
    build_model(cfg)
    assert os.environ["GOOGLE_API_KEY"] == "existing"  # pragma: allowlist secret


def test_set_default_model_priority(monkeypatch):
    monkeypatch.setenv("ADK_AGENT_MODEL", "litellm:openai/env-model")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from adk_agent import models

    models.set_default_model("litellm:openai/override-model")
    cfg = models._default_model_config()
    assert cfg.provider == "litellm"
    assert cfg.name == "openai/override-model"
    models.set_default_model(None)


def test_is_valid_model_spec():
    from adk_agent.models import is_valid_model_spec

    assert is_valid_model_spec("gemini:gemini-2.5-pro")
    assert is_valid_model_spec("litellm:deepseek/deepseek-v4-pro")
    assert is_valid_model_spec("claude:claude-sonnet-5-5")
    assert is_valid_model_spec("vertex:claude-3-5")
    assert is_valid_model_spec("openai/gpt-4o")  # bare id -> litellm
    assert not is_valid_model_spec("bogus:foo")
    assert not is_valid_model_spec("gemini:")
    assert not is_valid_model_spec("")
    assert not is_valid_model_spec("   ")
