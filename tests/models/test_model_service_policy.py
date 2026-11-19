"""SLICE-164: the model gateway resolves policy server-side, not from the caller."""

from __future__ import annotations

from fastapi.testclient import TestClient

from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelGatewayRequest,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.models.gateway import PolicyModelGateway
from adk_agent.models.service import build_model_gateway_app

AUTH = {"Authorization": "Bearer secret"}


class FakeProvider:
    name = "fake"
    egress = "none"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=2,
            egress="none",
        )


def _gateway() -> PolicyModelGateway:
    return PolicyModelGateway({"fake": FakeProvider()})


def _resolver(policy: ModelPolicy | None):
    async def resolve(_invocation: Invocation) -> ModelPolicy | None:
        return policy

    return resolve


def _body(provider: str = "fake", allow=("fake",)) -> dict:
    request = ModelGatewayRequest(
        invocation=Invocation(
            run_id="r1",
            trace_id="tr1",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
            input="hi",
        ),
        request=ModelRequest(
            provider=provider, model="m", messages=[Message(role="user", content="hi")]
        ),
        policy=ModelPolicy(provider_allowlist=list(allow)),
    )
    return request.model_dump(mode="json")


def test_gateway_ignores_caller_policy():
    # Caller policy allows "fake"; the manifest only allows "other". The gateway
    # must use the manifest policy and deny, not the caller's allowlist.
    app = build_model_gateway_app(
        _gateway(),
        auth_token="secret",
        policy_resolver=_resolver(ModelPolicy(provider_allowlist=["other"])),
    )
    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_body("fake", allow=("fake",)), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "model_denied"}


def test_gateway_uses_manifest_policy():
    app = build_model_gateway_app(
        _gateway(),
        auth_token="secret",
        policy_resolver=_resolver(ModelPolicy(provider_allowlist=["fake"])),
    )
    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_body("fake"), headers=AUTH)
    assert response.status_code == 200
    assert response.json()["text"] == "ok"


def test_gateway_fails_closed_without_resolver():
    app = build_model_gateway_app(_gateway(), auth_token="secret")
    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_body("fake"), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "policy_unavailable"}


def test_gateway_fails_closed_on_missing_policy():
    app = build_model_gateway_app(_gateway(), auth_token="secret", policy_resolver=_resolver(None))
    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_body("fake"), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "policy_unavailable"}
