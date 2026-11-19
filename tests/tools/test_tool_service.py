"""SLICE-033: the tool gateway HTTP service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adk_agent.core import (
    AgentRef,
    Invocation,
    Principal,
    ToolGatewayRequest,
    ToolGrant,
    ToolRequest,
)
from adk_agent.tools import FunctionRegistry, FunctionToolGateway, ToolSpec
from adk_agent.tools.service import build_tool_gateway_app

AUTH = {"Authorization": "Bearer secret"}


def add(a: int, b: int) -> int:
    return a + b


def opaque() -> object:
    return object()


def _gateway() -> FunctionToolGateway:
    registry = FunctionRegistry(
        [
            ToolSpec(tool_id="add", handler=add, data_classes=("internal",)),
            ToolSpec(tool_id="secret", handler=opaque, requires_approval=True),
            ToolSpec(tool_id="binary", handler=opaque),
        ]
    )
    return FunctionToolGateway(registry)


def _body(tool_id: str = "add", grants=("add",), args=None) -> dict:
    request = ToolGatewayRequest(
        invocation=Invocation(
            run_id="r1",
            trace_id="tr1",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
            input="hi",
        ),
        request=ToolRequest(tool_id=tool_id, args={"a": 1, "b": 2} if args is None else args),
        grants=[ToolGrant(tool_id=grant) for grant in grants],
    )
    return request.model_dump(mode="json")


def _resolver(grants):
    async def resolve(_invocation):
        return grants

    return resolve


_GRANTS = [ToolGrant(tool_id="add"), ToolGrant(tool_id="secret"), ToolGrant(tool_id="binary")]


def _app(grants=_GRANTS):
    return build_tool_gateway_app(
        _gateway(),
        auth_token="secret",
        grant_resolver=_resolver(list(grants)),
    )


def test_request_contract_roundtrip():
    request = ToolGatewayRequest.model_validate(_body())
    assert ToolGatewayRequest.model_validate_json(request.model_dump_json()) == request


def test_network_bind_requires_token():
    with pytest.raises(ValueError):
        build_tool_gateway_app(_gateway(), host="0.0.0.0", auth_token=None)


def test_healthz_open_and_invoke_protected():
    app = _app()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/v1/invoke", json=_body()).status_code == 401

        response = client.post("/v1/invoke", json=_body(), headers=AUTH)
    assert response.status_code == 200


def test_invoke_returns_output():
    app = _app()
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body(), headers=AUTH)
    assert response.json() == {"output": 3, "data_classes": ["internal"]}


def test_denied_grant_maps_to_403():
    app = _app([])
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body(grants=()), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "tool_denied"}


def test_unknown_tool_maps_to_403():
    app = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/invoke", json=_body(tool_id="nope", grants=("nope",)), headers=AUTH
        )
    assert response.status_code == 403


def test_approval_required_maps_to_403():
    app = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/invoke", json=_body(tool_id="secret", grants=("secret",)), headers=AUTH
        )
    assert response.status_code == 403


def test_unserializable_output_maps_to_502():
    app = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/invoke",
            json=_body(tool_id="binary", grants=("binary",), args={}),
            headers=AUTH,
        )
    assert response.status_code == 502
    assert response.json() == {"error": "tool_output_invalid"}
