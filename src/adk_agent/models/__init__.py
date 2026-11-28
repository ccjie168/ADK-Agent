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
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..adapters.adk import models as adk_models
from ..config import ModelConfig
from .breaker import BreakerProvider
from .gateway import ModelUnavailable
from .http_gateway import HttpModelGateway, ModelGatewayError
from .service import build_model_gateway_app, build_providers

if TYPE_CHECKING:  # pragma: no cover
    from ..adapters.adk.models import BaseLlm

_PROVIDER_PREFIXES = ("gemini", "litellm", "claude", "vertex")


@dataclass(frozen=True)
class ProviderCredentials:
    """What a model provider record contributes to a model configuration."""

    api_key: str | None = None
    api_base: str | None = None


ProviderLookup = Callable[[str, str], ProviderCredentials | None]

_provider_lookup: ProviderLookup | None = None


def set_provider_lookup(lookup: ProviderLookup | None) -> None:
    """Install the process-wide resolver for model provider records (ADR-0045)."""
    global _provider_lookup
    _provider_lookup = lookup


def clear_provider_lookup() -> None:
    set_provider_lookup(None)


def resolve_model_config(spec: str | ModelConfig | None = None) -> ModelConfig:
    """Normalize ``spec`` and fill credentials from a matching provider record.

    Records only fill fields the caller left unset; they never rename the model.
    """
    cfg = _normalize(spec)
    lookup = _provider_lookup
    if lookup is None:
        return cfg
    found = lookup(cfg.provider, cfg.name)
    if found is None:
        return cfg
    updates: dict[str, str] = {}
    if cfg.api_key is None and found.api_key:
        updates["api_key"] = found.api_key
    if cfg.api_base is None and found.api_base:
        updates["api_base"] = found.api_base
    return cfg.model_copy(update=updates) if updates else cfg


def build_model(spec: str | ModelConfig | None = None) -> BaseLlm:
    """Build an ADK model instance from a short string or a :class:`ModelConfig`.

    Short strings are parsed by provider prefix, e.g.::

        "gemini:gemini-2.5-pro"
        "litellm:deepseek/deepseek-v4-pro"
        "claude:claude-sonnet-5-5"

    A bare string without a recognised prefix is treated as a LiteLLM model id.
    """
    cfg = resolve_model_config(spec)

    if cfg.provider == "gemini":
        kwargs = dict(cfg.kwargs)
        if cfg.api_key:
            kwargs.setdefault("client_kwargs", {"api_key": cfg.api_key})
        return adk_models.gemini_model(cfg.name, **kwargs)

    if cfg.provider == "claude":
        # NB: ADK's ``Claude`` class is the *Vertex AI* variant. The plain
        # Anthropic-API adapter (used for Anthropic and Anthropic-compatible
        # endpoints such as DeepSeek's /anthropic) is ``AnthropicLlm``.
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
        return adk_models.claude_llm(cfg.name, **kwargs)

    if cfg.provider == "vertex":
        return adk_models.vertex_claude(cfg.name, **cfg.kwargs)

    # LiteLLM is the general escape hatch: deepseek/, openai/, anthropic/, ...
    kwargs = dict(cfg.kwargs)
    if cfg.api_key:
        kwargs.setdefault("api_key", cfg.api_key)
    if cfg.api_base:
        kwargs.setdefault("api_base", cfg.api_base)
    return adk_models.litellm_model(cfg.name, **kwargs)


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


_default_model_override: str | None = None


def set_default_model(spec: str | None) -> None:
    """Set the runtime global default model (ADR-0040).

    ``None`` clears the override and falls back to ``ADK_AGENT_MODEL``.
    """
    global _default_model_override
    _default_model_override = spec


def is_valid_model_spec(spec: str) -> bool:
    """True when ``spec`` has a recognised provider prefix or is a bare LiteLLM id.

    A bare id (no ``:``) is treated as LiteLLM, matching :func:`build_model`.
    """
    if not spec or not spec.strip():
        return False
    if ":" not in spec:
        return True
    provider, name = spec.split(":", 1)
    return provider in _PROVIDER_PREFIXES and bool(name.strip())


def effective_default_model() -> str:
    """Return the current global default model spec as ``provider:name`` (ADR-0040)."""
    cfg = _default_model_config()
    return f"{cfg.provider}:{cfg.name}"


def _default_model_config() -> ModelConfig:
    if _default_model_override is not None:
        return _normalize(_default_model_override)

    explicit = os.environ.get("ADK_AGENT_MODEL")
    if explicit:
        return _normalize(explicit)

    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return ModelConfig(provider="gemini", name="gemini-2.5-pro")

    return ModelConfig(provider="litellm", name="deepseek/deepseek-v4-pro")


__all__ = [
    "BreakerProvider",
    "HttpModelGateway",
    "ModelGatewayError",
    "ModelUnavailable",
    "ProviderCredentials",
    "build_model",
    "clear_provider_lookup",
    "build_model_gateway_app",
    "build_providers",
    "disable_thinking",
    "effective_default_model",
    "is_valid_model_spec",
    "resolve_model_config",
    "set_default_model",
    "set_provider_lookup",
]
