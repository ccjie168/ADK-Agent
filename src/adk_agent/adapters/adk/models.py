"""ADK model types and the provider constructors ``build_model`` uses."""

from __future__ import annotations

from typing import Any

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

__all__ = [
    "BaseLlm",
    "LlmRequest",
    "LlmResponse",
    "claude_llm",
    "gemini_model",
    "litellm_model",
    "vertex_claude",
]


def gemini_model(model: str, **kwargs: Any) -> BaseLlm:
    from google.adk.models import Gemini

    return Gemini(model=model, **kwargs)


def claude_llm(model: str, **kwargs: Any) -> BaseLlm:
    """The Anthropic API adapter (not the Vertex AI variant)."""
    from google.adk.models.anthropic_llm import AnthropicLlm

    return AnthropicLlm(model=model, **kwargs)


def vertex_claude(model: str, **kwargs: Any) -> BaseLlm:
    from google.adk.models import Claude

    return Claude(model=model, **kwargs)


def litellm_model(model: str, **kwargs: Any) -> BaseLlm:
    from google.adk.models import LiteLlm

    return LiteLlm(model=model, **kwargs)
