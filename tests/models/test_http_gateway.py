"""SLICE-032: the HTTP model gateway client."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.models.gateway import ModelDenied, PolicyModelGateway
from adk_agent.models.http_gateway import HttpModelGateway, ModelGatewayError
from adk_agent.models.service import build_model_gateway_app


class FakeProvider:
    name = "fake"
    egress = "none"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if self.error is not None:
            raise self.error
        return ModelResponse(
            text="from service",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=2,
            egress="none",
        )


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request(provider: str = "fake") -> ModelRequest:
    return ModelRequest(provider=provider, model="m", messages=[Message(role="user", content="hi")])


def _client(
    provider: FakeProvider | None = None,
    *,
    auth_token: str = "secret",
) -> tuple[HttpModelGateway, httpx.AsyncClient]:
    app = build_model_gateway_app(
        PolicyModelGateway({"fake": provider or FakeProvider()}),
        auth_token="secret",
    )
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    )
    return HttpModelGateway(
        "http://gateway", auth_token=auth_token, client=http_client
    ), http_client


def _complete(client: HttpModelGateway, policy: ModelPolicy | None = None):
    return asyncio.run(
        client.complete(
            _invocation(), _request(), policy or ModelPolicy(provider_allowlist=["fake"])
        )
    )


def test_client_roundtrip():
    client, http_client = _client()
    try:
        response = _complete(client)
    finally:
        asyncio.run(http_client.aclose())
    assert response.text == "from service"


def test_client_maps_denied():
    client, http_client = _client()
    try:
        with pytest.raises(ModelDenied):
            _complete(client, ModelPolicy(provider_allowlist=["litellm"]))
    finally:
        asyncio.run(http_client.aclose())


def test_client_rejects_bad_token():
    client, http_client = _client(auth_token="wrong")
    try:
        with pytest.raises(ModelGatewayError):
            _complete(client)
    finally:
        asyncio.run(http_client.aclose())


def test_client_maps_provider_failure():
    client, http_client = _client(FakeProvider(error=RuntimeError("boom upstream")))
    try:
        with pytest.raises(ModelGatewayError) as exc:
            _complete(client)
    finally:
        asyncio.run(http_client.aclose())
    assert "boom" not in str(exc.value)
