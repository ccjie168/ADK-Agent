"""SLICE-186: model alias router and fallback execution (ADR-0033 slice 2)."""

from __future__ import annotations

import asyncio

import pytest

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
from adk_agent.models.gateway import ModelDenied, ModelUnavailable, PolicyModelGateway
from adk_agent.models.routing import resolve_candidates


def _policy(*, allowlist=("litellm",), candidates=None, alias="primary") -> ModelPolicy:
    candidates = candidates or [
        ModelCandidate(provider="litellm", model="deepseek/deepseek-v4-pro"),
        ModelCandidate(
            provider="litellm",
            model="gemini/gemini-2.5-pro",
            allowed_data_classes=["public", "internal"],
        ),
    ]
    return ModelPolicy(
        provider_allowlist=list(allowlist),
        model_aliases=[ModelAlias(alias=alias, candidates=candidates)],
    )


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request() -> ModelRequest:
    return ModelRequest(
        provider="direct", model="direct-model", messages=[Message(role="user", content="hi")]
    )


class FakeProvider:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.egress = "third_party"
        self.fail = fail
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError(f"{self.name} down")
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            egress="third_party",
        )


def test_resolve_candidates_filters_allowlist():
    policy = _policy(
        candidates=[
            ModelCandidate(provider="vllm", model="local-1"),
            ModelCandidate(provider="litellm", model="deepseek/deepseek-v4-pro"),
        ]
    )
    resolved = resolve_candidates(policy, "primary", [])
    assert [candidate.model for candidate in resolved] == ["deepseek/deepseek-v4-pro"]


def test_resolve_candidates_filters_data_classes():
    policy = _policy()
    resolved = resolve_candidates(policy, "primary", ["confidential"])
    assert [candidate.model for candidate in resolved] == ["deepseek/deepseek-v4-pro"]
    assert len(resolve_candidates(policy, "primary", ["internal"])) == 2


def test_resolve_unknown_alias_denied():
    with pytest.raises(ModelDenied):
        resolve_candidates(_policy(), "missing", [])


def test_resolve_no_permitted_candidate_denied():
    policy = _policy(
        candidates=[ModelCandidate(provider="litellm", model="m1", allowed_data_classes=["public"])]
    )
    with pytest.raises(ModelDenied):
        resolve_candidates(policy, "primary", ["confidential"])


def _gateway(*providers: FakeProvider) -> PolicyModelGateway:
    return PolicyModelGateway({provider.name: provider for provider in providers})


def test_gateway_routes_alias_to_primary():
    primary = FakeProvider("litellm")
    gateway = _gateway(primary)
    response = asyncio.run(gateway.complete(_invocation(), _request(), _policy(), alias="primary"))
    assert response.model == "deepseek/deepseek-v4-pro"
    assert primary.requests[0].model == "deepseek/deepseek-v4-pro"


def test_gateway_falls_back_to_next_candidate():
    class PrimaryDownProvider(FakeProvider):
        async def complete(self, request: ModelRequest) -> ModelResponse:
            if request.model == "deepseek/deepseek-v4-pro":
                self.requests.append(request)
                raise ModelUnavailable("primary down")
            return await super().complete(request)

    provider = PrimaryDownProvider("litellm")
    gateway = PolicyModelGateway({"litellm": provider})
    response = asyncio.run(gateway.complete(_invocation(), _request(), _policy(), alias="primary"))
    assert response.model == "gemini/gemini-2.5-pro"
    assert [request.model for request in provider.requests] == [
        "deepseek/deepseek-v4-pro",
        "gemini/gemini-2.5-pro",
    ]


def test_gateway_all_candidates_fail():
    failing = FakeProvider("litellm", fail=True)
    gateway = _gateway(failing)
    with pytest.raises(ModelUnavailable):
        asyncio.run(gateway.complete(_invocation(), _request(), _policy(), alias="primary"))


def test_policy_denial_does_not_fall_over():
    backup = FakeProvider("backup")
    policy = _policy(
        allowlist=("litellm", "backup"),
        candidates=[
            ModelCandidate(provider="litellm", model="deepseek/deepseek-v4-pro"),
            ModelCandidate(provider="backup", model="gemini/gemini-2.5-pro"),
        ],
    )
    # litellm is allowed by policy but not configured here: the denial must surface
    # instead of silently degrading to the backup candidate.
    gateway = PolicyModelGateway({"backup": backup})
    with pytest.raises(ModelDenied):
        asyncio.run(gateway.complete(_invocation(), _request(), policy, alias="primary"))
    assert backup.requests == []


def test_direct_path_unchanged():
    direct = FakeProvider("direct")
    gateway = _gateway(direct)
    response = asyncio.run(
        gateway.complete(_invocation(), _request(), _policy(allowlist=("direct",)))
    )
    assert response.model == "direct-model"
    assert len(direct.requests) == 1
