"""Model factory: one place to select Gemini / Anthropic / LiteLLM / Vertex.

ADK ships several model classes. The framework hides the differences behind
:func:`build_model` so an agent can be re-pointed at a different backend from
configuration or a single env var.

Provider -> ADK class:

* ``gemini``  -> ``google.adk.models.Gemini`` (no extra dependency)
* ``claude``  -> ``google.adk.models.anthropic_llm.AnthropicLlm`` (plain
  Anthropic API; also works for Anthropic-compatible endpoints such as
  DeepSeek's ``/anthropic``). Needs ``anthropic``.
* ``vertex``  -> ``google.adk.models.Claude`` (Vertex AI variant; needs
  ``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_LOCATION``).
* ``litellm`` (default) -> ``google.adk.models.LiteLlm`` (needs ``litellm``).

Each provider is imported lazily, so installing only one backend's optional
dependency is enough.

Resolution order for ``build_model()`` with no argument:

1. ``ADK_AGENT_MODEL`` env var, e.g. ``claude:deepseek-v4-pro``,
   ``gemini:gemini-2.5-pro`` or ``litellm:deepseek/deepseek-v4-pro``.
2. If ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY`` is set -> Gemini.
3. Otherwise -> LiteLLM DeepSeek (``deepseek/deepseek-v4-pro``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .config import ModelConfig

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.models import BaseLlm

_PROVIDER_PREFIXES = ("gemini", "litellm", "claude", "vertex")


def build_model(spec: str | ModelConfig | None = None) -> BaseLlm:
    """Build an ADK model instance from a short string or a :class:`ModelConfig`.

    Short strings are parsed by provider prefix, e.g.::

        "gemini:gemini-2.5-pro"
        "litellm:deepseek/deepseek-v4-pro"
        "claude:claude-sonnet-5-5"

    A bare string without a recognised prefix is treated as a LiteLLM model id.
    """
    cfg = _normalize(spec)

    if cfg.provider == "gemini":
        from google.adk.models import Gemini

        kwargs = dict(cfg.kwargs)
        if cfg.api_key:
            kwargs.setdefault("client_kwargs", {"api_key": cfg.api_key})
        return Gemini(model=cfg.name, **kwargs)

    if cfg.provider == "claude":
        # NB: google.adk.models.Claude is the *Vertex AI* variant. The plain
        # Anthropic-API adapter (used for Anthropic and Anthropic-compatible
        # endpoints such as DeepSeek's /anthropic) is AnthropicLlm.
        from google.adk.models.anthropic_llm import AnthropicLlm

        kwargs = dict(cfg.kwargs)
        # AnthropicLlm takes an Anthropic *client*, not api_key/base_url. With
        # neither set it builds AsyncAnthropic(), which reads ANTHROPIC_API_KEY,
        # ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL from the environment.
        if cfg.api_key or cfg.api_base:
            from anthropic import AsyncAnthropic

            client_kwargs: dict = {}
            if cfg.api_key:
                client_kwargs["api_key"] = cfg.api_key
            if cfg.api_base:
                client_kwargs["base_url"] = cfg.api_base
            kwargs.setdefault("client", AsyncAnthropic(**client_kwargs))
        return AnthropicLlm(model=cfg.name, **kwargs)

    if cfg.provider == "vertex":
        from google.adk.models import Claude

        return Claude(model=cfg.name, **cfg.kwargs)

    # LiteLLM is the general escape hatch: deepseek/, openai/, anthropic/, ...
    from google.adk.models import LiteLlm

    kwargs = dict(cfg.kwargs)
    if cfg.api_key:
        kwargs.setdefault("api_key", cfg.api_key)
    if cfg.api_base:
        kwargs.setdefault("api_base", cfg.api_base)
    return LiteLlm(model=cfg.name, **kwargs)


def disable_thinking() -> Any:
    """Return a ``GenerateContentConfig`` with thinking disabled.

    Anthropic-compatible third-party endpoints (DeepSeek's ``/anthropic``, for
    example) reject ``redacted_thinking`` blocks in the conversation history,
    so a second turn with the same session fails with 422. Disabling thinking
    keeps the history to text/tool blocks and multi-turn chat works.
    """
    from google.genai import types

    return types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))


def _normalize(spec: str | ModelConfig | None) -> ModelConfig:
    if isinstance(spec, ModelConfig):
        return spec

    if spec is None:
        return _default_model_config()

    if ":" in spec:
        provider, name = spec.split(":", 1)
        if provider in _PROVIDER_PREFIXES:
            return ModelConfig(provider=provider, name=name)  # type: ignore[arg-type]

    return ModelConfig(provider="litellm", name=spec)


def _default_model_config() -> ModelConfig:
    explicit = os.environ.get("ADK_AGENT_MODEL")
    if explicit:
        return _normalize(explicit)

    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return ModelConfig(provider="gemini", name="gemini-2.5-pro")

    return ModelConfig(provider="litellm", name="deepseek/deepseek-v4-pro")
