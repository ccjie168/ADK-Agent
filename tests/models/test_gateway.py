"""SLICE-013: the model gateway enforces policy and audits every call."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import (
    AgentRef,
    Invocation,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.models.gateway import ModelDenied, PolicyModelGateway


class FakeProvider:
    name = "litellm"
    egress = "third_party"

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.seen = None

    async def complete(self, request):
        self.seen = request
        if self.error:
            raise self.error
        return self.response


class FakeAudit:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _request(provider: str = "litellm") -> ModelRequest:
    return ModelRequest(
        provider=provider,
        model="deepseek/deepseek-v4-pro",
        messages=[{"role": "user", "content": "hi"}],
    )


def _response() -> ModelResponse:
    return ModelResponse(
        text="hello",
        provider="litellm",
        model="deepseek/deepseek-v4-pro",
        input_tokens=3,
        output_tokens=2,
        cost_usd=0.01,
        egress="third_party",
    )


def _policy(*providers: str) -> ModelPolicy:
    return ModelPolicy(provider_allowlist=list(providers))


def test_allowed_provider_is_audited():
    provider = FakeProvider(response=_response())
    audit = FakeAudit()
    gateway = PolicyModelGateway({"litellm": provider}, audit=audit)

    result = asyncio.run(gateway.complete(_invocation(), _request(), _policy("litellm")))

    assert result == _response()
    assert provider.seen == _request()
    [event] = audit.events
    assert event.action == "model.call"
    assert event.target == "litellm:deepseek/deepseek-v4-pro"
    assert event.status == "ok"
    assert event.tokens == 5
    assert event.cost_usd == 0.01
    assert event.egress == "third_party"
    assert event.trace_id == "tr1"
    assert event.args_hash
    assert event.result_hash


def test_unlisted_provider_is_denied_and_audited():
    audit = FakeAudit()
    gateway = PolicyModelGateway({"litellm": FakeProvider(response=_response())}, audit=audit)

    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request(), _policy("vllm")))

    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "provider_not_allowed"
    assert event.egress == "none"


def test_unconfigured_provider_is_denied():
    audit = FakeAudit()
    gateway = PolicyModelGateway({}, audit=audit)

    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request(), _policy("litellm")))

    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "provider_unavailable"


def test_provider_error_is_audited_and_reraised():
    audit = FakeAudit()
    provider = FakeProvider(error=RuntimeError("boom"))
    gateway = PolicyModelGateway({"litellm": provider}, audit=audit)

    with pytest.raises(RuntimeError):
        asyncio.run(gateway.complete(_invocation(), _request(), _policy("litellm")))

    [event] = audit.events
    assert event.status == "error"
    assert event.error_code == "RuntimeError"


def test_provider_key_must_match_name():
    with pytest.raises(ValueError):
        PolicyModelGateway({"other": FakeProvider()})
