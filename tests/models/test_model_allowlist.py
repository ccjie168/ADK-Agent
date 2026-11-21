"""SLICE-205: model_allowlist is enforced for direct calls and alias routing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.adk.models import BaseLlm
from google.genai import types

from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelAlias,
    ModelCandidate,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.core.context import reset_invocation, set_invocation
from adk_agent.models.gateway import ModelDenied, PolicyModelGateway
from adk_agent.models.gateway_llm import GatewayLlm
from adk_agent.models.routing import resolve_candidates


class FakeProvider:
    name = "litellm"
    egress = "third_party"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            text="hello",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            egress="third_party",
        )


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request(model: str) -> ModelRequest:
    return ModelRequest(
        provider="litellm",
        model=model,
        messages=[Message(role="user", content="hi")],
    )


def _policy(models: list[str]) -> ModelPolicy:
    return ModelPolicy(provider_allowlist=["litellm"], model_allowlist=models)


def test_direct_request_outside_model_allowlist_is_denied():
    provider = FakeProvider()
    audit = FakeAudit()
    gateway = PolicyModelGateway({"litellm": provider}, audit=audit)

    with pytest.raises(ModelDenied):
        asyncio.run(
            gateway.complete(
                _invocation(),
                _request("gemini/gemini-2.5-pro"),
                _policy(["deepseek/deepseek-v4-pro"]),
            )
        )

    assert provider.requests == []


def test_denied_model_is_audited():
    audit = FakeAudit()
    gateway = PolicyModelGateway({"litellm": FakeProvider()}, audit=audit)

    with pytest.raises(ModelDenied):
        asyncio.run(
            gateway.complete(
                _invocation(),
                _request("gemini/gemini-2.5-pro"),
                _policy(["deepseek/deepseek-v4-pro"]),
            )
        )

    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "model_not_allowed"
    assert event.egress == "none"


def test_direct_request_inside_model_allowlist_is_served():
    provider = FakeProvider()
    gateway = PolicyModelGateway({"litellm": provider})

    result = asyncio.run(
        gateway.complete(
            _invocation(),
            _request("deepseek/deepseek-v4-pro"),
            _policy(["deepseek/deepseek-v4-pro"]),
        )
    )

    assert result.model == "deepseek/deepseek-v4-pro"


def test_empty_model_allowlist_admits_any_model():
    provider = FakeProvider()
    gateway = PolicyModelGateway({"litellm": provider})

    result = asyncio.run(gateway.complete(_invocation(), _request("anything/at-all"), _policy([])))

    assert result.model == "anything/at-all"


def test_alias_candidates_are_filtered_by_model_allowlist():
    policy = ModelPolicy(
        provider_allowlist=["litellm"],
        model_allowlist=["second-model"],
        model_aliases=[
            ModelAlias(
                alias="primary",
                candidates=[
                    ModelCandidate(provider="litellm", model="first-model"),
                    ModelCandidate(provider="litellm", model="second-model"),
                ],
            )
        ],
    )

    candidates = resolve_candidates(policy, "primary", [])

    assert [candidate.model for candidate in candidates] == ["second-model"]


def test_alias_without_allowed_candidate_is_denied():
    policy = ModelPolicy(
        provider_allowlist=["litellm"],
        model_allowlist=["second-model"],
        model_aliases=[
            ModelAlias(
                alias="primary",
                candidates=[ModelCandidate(provider="litellm", model="first-model")],
            )
        ],
    )

    with pytest.raises(ModelDenied):
        resolve_candidates(policy, "primary", [])


def test_provider_denial_wins_over_model_check():
    audit = FakeAudit()
    gateway = PolicyModelGateway({"litellm": FakeProvider()}, audit=audit)
    policy = ModelPolicy(provider_allowlist=["vllm"], model_allowlist=["deepseek/deepseek-v4-pro"])

    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request("gemini/gemini-2.5-pro"), policy))

    [event] = audit.events
    assert event.error_code == "provider_not_allowed"


def test_alias_without_permitted_candidate_is_audited():
    audit = FakeAudit()
    gateway = PolicyModelGateway({"litellm": FakeProvider()}, audit=audit)
    policy = ModelPolicy(
        provider_allowlist=["litellm"],
        model_allowlist=["second-model"],
        model_aliases=[
            ModelAlias(
                alias="primary",
                candidates=[ModelCandidate(provider="litellm", model="first-model")],
            )
        ],
    )

    with pytest.raises(ModelDenied):
        asyncio.run(
            gateway.complete(_invocation(), _request("first-model"), policy, alias="primary")
        )

    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "alias_not_allowed"
    assert event.model_alias == "primary"
    assert event.egress == "none"


async def _drain(gateway: GatewayLlm, request: SimpleNamespace) -> None:
    async for _ in gateway.generate_content_async(request):
        pass


def test_gateway_llm_enforces_model_allowlist():
    audit = FakeAudit()

    class Delegate(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            yield None

    gateway = GatewayLlm(
        model="gemini-2.5-pro",
        delegate=Delegate(model="gemini-2.5-pro"),
        provider="gemini",
        policy=ModelPolicy(provider_allowlist=["gemini"], model_allowlist=["allowed-model"]),
        audit=audit,
    )
    request = SimpleNamespace(
        contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
        model="gemini-2.5-pro",
    )
    token = set_invocation(_invocation())
    try:
        with pytest.raises(ModelDenied):
            asyncio.run(_drain(gateway, request))
    finally:
        reset_invocation(token)

    [event] = audit.events
    assert event.error_code == "model_not_allowed"
