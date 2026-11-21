"""ADK model wrapper that enforces policy and audits model calls."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from ..audit.hashing import hash_json, hash_text
from ..core import ModelPolicy
from ..core.context import current_invocation
from .gateway import (
    ModelDenied,
    check_model,
    check_provider,
    egress_for,
    emit_model_audit,
)

_PROVIDERS = {
    "Gemini": "gemini",
    "AnthropicLlm": "claude",
    "LiteLlm": "litellm",
    "Claude": "vertex",
}


def provider_for_model(model: BaseLlm) -> str:
    return _PROVIDERS.get(type(model).__name__, type(model).__name__.lower())


def _contents_hash(contents: Any) -> str:
    payload = [
        content.model_dump(mode="json", exclude_none=True)
        if hasattr(content, "model_dump")
        else str(content)
        for content in contents or []
    ]
    return hash_json(payload)


def _response_text(response: Any) -> str:
    content = getattr(response, "content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(part.text for part in parts if getattr(part, "text", None))


def _response_tokens(response: Any) -> int | None:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
    completion = int(getattr(usage, "candidates_token_count", 0) or 0)
    return prompt + completion


class GatewayLlm(BaseLlm):
    """Delegate to another model, enforcing policy and auditing each call."""

    delegate: BaseLlm
    provider: str
    policy: ModelPolicy
    audit: Any | None = None

    @property
    def capabilities(self):
        return self.delegate.capabilities

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        invocation = current_invocation()
        if invocation is None:
            raise ModelDenied("model call outside an invocation context")

        started = time.perf_counter()
        args_hash = _contents_hash(getattr(llm_request, "contents", None))
        model_name = getattr(llm_request, "model", None) or self.model
        egress = egress_for(self.provider)

        try:
            check_provider(self.provider, self.policy)
        except ModelDenied:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=self.provider,
                model=model_name,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress=egress,
                status="denied",
                error_code="provider_not_allowed",
                started=started,
            )
            raise

        try:
            check_model(model_name, self.policy)
        except ModelDenied:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=self.provider,
                model=model_name,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress=egress,
                status="denied",
                error_code="model_not_allowed",
                started=started,
            )
            raise

        last: Any = None
        try:
            async for response in self.delegate.generate_content_async(llm_request, stream=stream):
                last = response
                yield response
        except Exception as exc:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=self.provider,
                model=model_name,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress=egress,
                status="error",
                error_code=type(exc).__name__,
                started=started,
            )
            raise

        text = _response_text(last) if last is not None else ""
        await emit_model_audit(
            self.audit,
            invocation,
            provider=self.provider,
            model=model_name,
            args_hash=args_hash,
            result_hash=hash_text(text),
            tokens=_response_tokens(last) if last is not None else None,
            cost_usd=None,
            egress=egress,
            status="ok",
            error_code=None,
            started=started,
        )
