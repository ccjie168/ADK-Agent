"""SLICE-032: the model gateway HTTP service."""

from __future__ import annotations

import pytest
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
from adk_agent.models.service import build_model_gateway_app, build_providers

AUTH = {"Authorization": "Bearer secret"}


class FakeProvider:
    name = "fake"
    egress = "none"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if self.error is not None:
            raise self.error
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=2,
            egress="none",
        )


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


def _gateway(provider: FakeProvider | None = None) -> PolicyModelGateway:
    return PolicyModelGateway({"fake": provider or FakeProvider()})


def test_request_contract_roundtrip():
    request = ModelGatewayRequest.model_validate(_body())
    assert ModelGatewayRequest.model_validate_json(request.model_dump_json()) == request


def test_build_providers():
    providers = build_providers(["litellm"])
    assert set(providers) == {"litellm"}

    vllm = build_providers(["vllm"], vllm_url="http://vllm:8000")
    assert set(vllm) == {"vllm"}

    with pytest.raises(ValueError):
        build_providers(["vllm"])
    with pytest.raises(ValueError):
        build_providers(["nope"])


def test_network_bind_requires_token():
    with pytest.raises(ValueError):
        build_model_gateway_app(_gateway(), host="0.0.0.0", auth_token=None)


def test_healthz_open_and_rpc_protected():
    app = build_model_gateway_app(_gateway(), auth_token="secret")
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/v1/complete", json=_body()).status_code == 401

        response = client.post("/v1/complete", json=_body(), headers=AUTH)
    assert response.status_code == 200
    assert response.json()["text"] == "ok"


def test_policy_denied_maps_to_403():
    app = build_model_gateway_app(_gateway(), auth_token="secret")
    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_body("other"), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "model_denied"}


def test_provider_failure_maps_to_502_without_details():
    app = build_model_gateway_app(
        _gateway(FakeProvider(error=RuntimeError("secret upstream url"))),
        auth_token="secret",
    )
    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_body(), headers=AUTH)
    assert response.status_code == 502
    assert response.json() == {"error": "model_call_failed"}
