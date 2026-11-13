"""SLICE-050: the model and tool gateways expose metrics."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelGatewayRequest,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
    ToolGatewayRequest,
    ToolGrant,
    ToolRequest,
)
from adk_agent.metrics import MetricsRegistry
from adk_agent.models.gateway import PolicyModelGateway
from adk_agent.models.service import build_model_gateway_app
from adk_agent.tools import FunctionRegistry, FunctionToolGateway, ToolSpec
from adk_agent.tools.service import build_tool_gateway_app

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
            output_tokens=1,
            egress="none",
        )


def add(a: int, b: int) -> int:
    return a + b


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _model_payload(allowlist: list[str]) -> dict[str, Any]:
    return ModelGatewayRequest(
        invocation=_invocation(),
        request=ModelRequest(
            provider="fake", model="m", messages=[Message(role="user", content="hi")]
        ),
        policy=ModelPolicy(provider_allowlist=allowlist),
    ).model_dump(mode="json")


def _tool_payload(grants: list[ToolGrant]) -> dict[str, Any]:
    return ToolGatewayRequest(
        invocation=_invocation(),
        request=ToolRequest(tool_id="add", args={"a": 1, "b": 2}),
        grants=grants,
    ).model_dump(mode="json")


def test_model_gateway_counts_calls():
    metrics = MetricsRegistry()
    app = build_model_gateway_app(
        PolicyModelGateway({"fake": FakeProvider()}), auth_token="secret", metrics=metrics
    )

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/v1/complete", json=_model_payload(["fake"]), headers=AUTH
            )
            metrics_response = await client.get("/metrics", headers=AUTH)
        assert response.status_code == 200
        return metrics_response

    text = asyncio.run(scenario()).text
    assert 'adk_model_calls_total{provider="fake",status="ok"} 1' in text
    assert 'adk_model_call_duration_seconds_count{provider="fake"} 1' in text


def test_model_gateway_counts_denials():
    metrics = MetricsRegistry()
    app = build_model_gateway_app(
        PolicyModelGateway({"fake": FakeProvider()}), auth_token="secret", metrics=metrics
    )

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            denied = await client.post(
                "/v1/complete", json=_model_payload(["litellm"]), headers=AUTH
            )
            assert denied.status_code == 403
            return await client.get("/metrics", headers=AUTH)

    text = asyncio.run(scenario()).text
    assert 'adk_model_calls_total{provider="fake",status="denied"} 1' in text


def test_model_metrics_require_token():
    app = build_model_gateway_app(
        PolicyModelGateway({"fake": FakeProvider()}),
        auth_token="secret",
        metrics=MetricsRegistry(),
    )

    async def scenario() -> int:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/metrics")
        return response.status_code

    assert asyncio.run(scenario()) == 401


def test_tool_gateway_counts_calls():
    metrics = MetricsRegistry()
    registry = FunctionRegistry([ToolSpec(tool_id="add", handler=add)])
    app = build_tool_gateway_app(
        FunctionToolGateway(registry), auth_token="secret", metrics=metrics
    )

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            ok = await client.post(
                "/v1/invoke", json=_tool_payload([ToolGrant(tool_id="add")]), headers=AUTH
            )
            denied = await client.post("/v1/invoke", json=_tool_payload([]), headers=AUTH)
            assert ok.status_code == 200
            assert denied.status_code == 403
            return await client.get("/metrics", headers=AUTH)

    text = asyncio.run(scenario()).text
    assert 'adk_tool_calls_total{status="ok",tool="add"} 1' in text
    assert 'adk_tool_calls_total{status="denied",tool="add"} 1' in text
    assert 'adk_tool_call_duration_seconds_count{tool="add"} 2' in text


def test_tool_metrics_require_token():
    registry = FunctionRegistry([ToolSpec(tool_id="add", handler=add)])
    app = build_tool_gateway_app(
        FunctionToolGateway(registry), auth_token="secret", metrics=MetricsRegistry()
    )

    async def scenario() -> int:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/metrics")
        return response.status_code

    assert asyncio.run(scenario()) == 401
