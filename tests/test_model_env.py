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
