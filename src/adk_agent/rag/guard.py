"""Prompt-injection detection and low-confidence refusal for RAG (ADR-0032)."""

from __future__ import annotations

import re

from .service import Citation

_DEFAULT_INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"disregard\s+(?:all\s+)?previous\s+instructions",
    r"system\s+prompt",
    r"pretend\s+you\s+are",
    r"you\s+are\s+now",
)


def detect_prompt_injection(text: str, patterns: tuple[str, ...] | None = None) -> bool:
    """Return True when the text matches a known prompt-injection pattern."""
    for pattern in patterns or _DEFAULT_INJECTION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


class RagGuard:
    """Filters retrieved citations by confidence and prompt-injection detection."""

    def __init__(
        self,
        min_confidence: float = 0.5,
        injection_patterns: tuple[str, ...] | None = None,
    ) -> None:
        self.min_confidence = min_confidence
        self.injection_patterns = injection_patterns

    def filter(self, citations: list[Citation]) -> list[Citation]:
        return [
            citation
            for citation in citations
            if citation.confidence >= self.min_confidence
            and not detect_prompt_injection(citation.snippet, self.injection_patterns)
        ]


__all__ = ["RagGuard", "detect_prompt_injection"]
