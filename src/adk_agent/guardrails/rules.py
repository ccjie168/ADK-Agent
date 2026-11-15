"""Guardrail rule models, built-in defaults, and config loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class GuardrailConfigError(ValueError):
    """The guardrail file is missing, malformed, or has an invalid pattern."""


class GuardrailRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    action: Literal["block", "redact"]
    applies_to: Literal["input", "output", "both"] = "both"
    pattern: str = Field(min_length=1)
    replacement: str = "[redacted]"
    enabled: bool = True


DEFAULT_RULES = (
    GuardrailRule(
        id="pii.email",
        action="redact",
        pattern=r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    ),
    GuardrailRule(
        id="pii.phone_cn",
        action="redact",
        pattern=r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)",
    ),
    GuardrailRule(
        id="pii.id_card_cn",
        action="redact",
        pattern=r"(?<!\d)\d{17}[\dXx](?!\d)",
    ),
    GuardrailRule(
        id="injection.ignore_previous",
        action="block",
        applies_to="input",
        pattern=r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
    ),
    GuardrailRule(
        id="injection.reveal_prompt",
        action="block",
        applies_to="input",
        pattern=r"(?i)(?:reveal|show|print)\s+(?:the\s+)?(?:system|hidden)\s+prompt",
    ),
    GuardrailRule(
        id="injection.zh_ignore",
        action="block",
        applies_to="input",
        pattern=r"忽略(?:之前|以上|前面)(?:的)?(?:所有)?指令",
    ),
    GuardrailRule(
        id="injection.zh_prompt",
        action="block",
        applies_to="input",
        pattern=r"(?:输出|显示|打印)(?:你的)?(?:系统|隐藏)提示词",
    ),
)


class GuardrailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    rules: list[GuardrailRule] = Field(default_factory=lambda: list(DEFAULT_RULES))


def load_guardrail_config(path: str | Path | None) -> GuardrailConfig | None:
    """Return None when no path is given, else the validated config."""
    if path is None:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise GuardrailConfigError("cannot read guardrail config") from exc
    except json.JSONDecodeError as exc:
        raise GuardrailConfigError("guardrail config is not valid JSON") from exc
    try:
        return GuardrailConfig.model_validate(payload)
    except ValidationError as exc:
        raise GuardrailConfigError("guardrail config does not match the schema") from exc


__all__ = [
    "DEFAULT_RULES",
    "GuardrailConfig",
    "GuardrailConfigError",
    "GuardrailRule",
    "load_guardrail_config",
]
