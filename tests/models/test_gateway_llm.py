"""SLICE-017: the gateway wraps ADK model calls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.adk.models import BaseLlm
from google.genai import types

from adk_agent.core import AgentRef, Invocation, ModelPolicy, Principal
from adk_agent.core.context import reset_invocation, set_invocation
from adk_agent.models import build_model
from adk_agent.models.gateway import ModelDenied
from adk_agent.models.gateway_llm import GatewayLlm, egress_for, provider_for_model


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [FakePart(text)]


class FakeUsage:
    prompt_token_count = 3
    candidates_token_count = 2


class FakeResponse:
    content = FakeContent("hello")
    usage_metadata = FakeUsage()


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


def _delegate(called: list) -> BaseLlm:
    class FakeDelegate(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            called.append(True)
            yield FakeResponse()

    return FakeDelegate(model="gemini-2.5-pro")


def _error_delegate() -> BaseLlm:
    class ErrorDelegate(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    return ErrorDelegate(model="gemini-2.5-pro")


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
        model="gemini-2.5-pro",
    )


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _collect_with_context(gateway: GatewayLlm, request):
    async def scenario():
        token = set_invocation(_invocation())
        try:
            return [response async for response in gateway.generate_content_async(request)]
        finally:
            reset_invocation(token)

    return asyncio.run(scenario())


def _gateway(delegate: BaseLlm, *, providers=("gemini",), audit=None) -> GatewayLlm:
    return GatewayLlm(
        model="gemini-2.5-pro",
        delegate=delegate,
        provider="gemini",
        policy=ModelPolicy(provider_allowlist=list(providers)),
        audit=audit,
    )


def test_delegates_and_audits():
    called: list = []
    auditor = FakeAudit()
    gateway = _gateway(_delegate(called), audit=auditor)

    responses = _collect_with_context(gateway, _request())

    assert len(responses) == 1
    assert called == [True]
    [event] = auditor.events
    assert event.action == "model.call"
    assert event.target == "gemini:gemini-2.5-pro"
    assert event.status == "ok"
    assert event.tokens == 5
    assert event.egress == "third_party"
    assert event.run_id == "r1"
    assert event.trace_id == "tr1"
    assert event.args_hash
    assert event.result_hash


def test_denied_provider_is_not_called():
    called: list = []
    auditor = FakeAudit()
    gateway = _gateway(_delegate(called), providers=("vllm",), audit=auditor)

    with pytest.raises(ModelDenied):
        _collect_with_context(gateway, _request())

    assert called == []
    [event] = auditor.events
    assert event.status == "denied"
    assert event.error_code == "provider_not_allowed"


def test_requires_invocation_context():
    gateway = _gateway(_delegate([]))

    async def scenario():
        return [response async for response in gateway.generate_content_async(_request())]

    with pytest.raises(ModelDenied):
        asyncio.run(scenario())


def test_delegate_error_is_audited():
    auditor = FakeAudit()
    gateway = _gateway(_error_delegate(), audit=auditor)

    with pytest.raises(RuntimeError):
        _collect_with_context(gateway, _request())

    [event] = auditor.events
    assert event.status == "error"
    assert event.error_code == "RuntimeError"


def test_provider_and_egress_helpers():
    assert provider_for_model(build_model("gemini:gemini-2.5-pro")) == "gemini"
    assert egress_for("vllm") == "none"
    assert egress_for("gemini") == "third_party"
