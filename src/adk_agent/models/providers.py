"""Model provider adapters. Both speak through LiteLLM; vLLM is OpenAI-compatible."""

from __future__ import annotations

from typing import Any, Literal

from ..core import ModelRequest, ModelResponse


def _to_response(
    request: ModelRequest,
    response: Any,
    *,
    egress: Literal["none", "third_party"],
) -> ModelResponse:
    choice = response.choices[0].message
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    hidden = getattr(response, "_hidden_params", None) or {}
    cost = hidden.get("response_cost")
    return ModelResponse(
        text=choice.content or "",
        provider=request.provider,
        model=request.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=float(cost) if cost is not None else None,
        egress=egress,
    )


class LiteLlmProvider:
    name = "litellm"
    egress: Literal["none", "third_party"] = "third_party"

    def __init__(self, *, api_key: str | None = None, api_base: str | None = None) -> None:
        self.api_key = api_key
        self.api_base = api_base

    async def complete(self, request: ModelRequest) -> ModelResponse:
        import litellm

        response = await litellm.acompletion(
            model=request.model,
            messages=[message.model_dump() for message in request.messages],
            max_tokens=request.max_output_tokens,
            temperature=request.temperature,
            api_key=self.api_key,
            api_base=self.api_base,
        )
        return _to_response(request, response, egress=self.egress)


class VllmProvider:
    name = "vllm"
    egress: Literal["none", "third_party"] = "none"

    def __init__(self, base_url: str, *, api_key: str = "not-needed") -> None:
        self.base_url = base_url
        self.api_key = api_key

    async def complete(self, request: ModelRequest) -> ModelResponse:
        import litellm

        response = await litellm.acompletion(
            model=f"openai/{request.model}",
            messages=[message.model_dump() for message in request.messages],
            max_tokens=request.max_output_tokens,
            temperature=request.temperature,
            api_base=self.base_url,
            api_key=self.api_key,
        )
        return _to_response(request, response, egress=self.egress)
