"""Input and output guardrail evaluation. Failures close the request."""

from __future__ import annotations

import re
from re import Pattern
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .rules import GuardrailConfig, GuardrailConfigError, GuardrailRule

Direction = Literal["input", "output"]


class GuardrailResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    redacted_by: list[str] = Field(default_factory=list)
    blocked_by: str | None = None
    error: str | None = None


class GuardrailPipeline:
    def __init__(self, config: GuardrailConfig) -> None:
        self._rules: list[tuple[GuardrailRule, Pattern[str]]] = []
        for rule in config.rules:
            if not rule.enabled:
                continue
            try:
                pattern = re.compile(rule.pattern)
            except re.error as exc:
                raise GuardrailConfigError(f"invalid pattern in rule {rule.id!r}") from exc
            self._rules.append((rule, pattern))

    def check(self, text: str, *, direction: Direction) -> GuardrailResult:
        redacted: list[str] = []
        current = text
        for rule, pattern in self._rules:
            if rule.applies_to not in (direction, "both"):
                continue
            try:
                matched, updated = self._evaluate(rule, pattern, current)
            except Exception:  # noqa: BLE001  # guardrail failure must fail closed
                return GuardrailResult(text=text, blocked_by=rule.id, error="guardrail_error")
            if rule.action == "block":
                if matched:
                    return GuardrailResult(text=text, blocked_by=rule.id)
                continue
            if matched:
                redacted.append(rule.id)
                current = updated
        return GuardrailResult(text=current, redacted_by=redacted)

    def _evaluate(self, rule: GuardrailRule, pattern: Pattern[str], text: str) -> tuple[bool, str]:
        if rule.action == "block":
            return bool(pattern.search(text)), text
        updated = pattern.sub(rule.replacement, text)
        return updated != text, updated


__all__ = ["Direction", "GuardrailPipeline", "GuardrailResult"]
