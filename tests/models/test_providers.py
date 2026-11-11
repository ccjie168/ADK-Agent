"""SLICE-013: LiteLLM and vLLM adapters build the right requests."""

from __future__ import annotations

import asyncio
import sys
import types

from adk_agent.core import ModelRequest
from adk_agent.models.providers import LiteLlmProvider, VllmProvider


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Usage:
    prompt_tokens = 4
    completion_tokens = 6


class _Response:
    choices = [_Choice("hello")]
    usage = _Usage()
    _hidden_params = {"response_cost": 0.02}


def _fake_litellm(monkeypatch, captured: dict) -> None:
    async def acompletion(**kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(acompletion=acompletion))


def _request(provider: str = "litellm") -> ModelRequest:
    return ModelRequest(
        provider=provider,
        model="deepseek/deepseek-v4-pro",
        messages=[{"role": "user", "content": "hi"}],
        max_output_tokens=64,
        temperature=0.2,
    )


def test_litellm_provider_builds_request(monkeypatch):
    captured: dict = {}
    _fake_litellm(monkeypatch, captured)
    provider = LiteLlmProvider(api_key="k", api_base="https://example")

    result = asyncio.run(provider.complete(_request()))

    assert captured["model"] == "deepseek/deepseek-v4-pro"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["max_tokens"] == 64
    assert captured["temperature"] == 0.2
    assert captured["api_key"] == "k"
    assert captured["api_base"] == "https://example"
    assert result.text == "hello"
    assert result.input_tokens == 4
    assert result.output_tokens == 6
    assert result.cost_usd == 0.02
    assert result.egress == "third_party"


def test_vllm_provider_is_local(monkeypatch):
    captured: dict = {}
    _fake_litellm(monkeypatch, captured)
    provider = VllmProvider("http://127.0.0.1:8000/v1")

    result = asyncio.run(provider.complete(_request("vllm")))

    assert captured["model"] == "openai/deepseek/deepseek-v4-pro"
    assert captured["api_base"] == "http://127.0.0.1:8000/v1"
    assert captured["api_key"] == "not-needed"  # pragma: allowlist secret
    assert result.egress == "none"
