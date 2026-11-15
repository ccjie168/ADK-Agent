"""Input and output guardrails for model calls."""

from __future__ import annotations

from .pipeline import Direction, GuardrailPipeline, GuardrailResult
from .rules import (
    DEFAULT_RULES,
    GuardrailConfig,
    GuardrailConfigError,
    GuardrailRule,
    load_guardrail_config,
)


def build_guardrail_pipeline(path: str | None) -> GuardrailPipeline | None:
    config = load_guardrail_config(path)
    return GuardrailPipeline(config) if config is not None else None


__all__ = [
    "DEFAULT_RULES",
    "Direction",
    "GuardrailConfig",
    "GuardrailConfigError",
    "GuardrailPipeline",
    "GuardrailResult",
    "GuardrailRule",
    "build_guardrail_pipeline",
    "load_guardrail_config",
]
