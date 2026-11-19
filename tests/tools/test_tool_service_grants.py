"""SLICE-165: the tool gateway resolves grants server-side, not from the caller."""

from __future__ import annotations

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


def _gateway() -> FunctionToolGateway:
    registry = FunctionRegistry([ToolSpec(tool_id="add", handler=add, data_classes=("internal",))])
    return FunctionToolGateway(registry)


def _resolver(grants):
    async def resolve(_invocation):
        return grants

    return resolve


def _body(tool_id: str = "add", grants=("add",)) -> dict:
    request = ToolGatewayRequest(
        invocation=Invocation(
            run_id="r1",
            trace_id="tr1",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
            input="hi",
        ),
        request=ToolRequest(tool_id=tool_id, args={"a": 1, "b": 2}),
        grants=[ToolGrant(tool_id=grant) for grant in grants],
    )
    return request.model_dump(mode="json")


def test_tool_gateway_ignores_caller_grants():
    # Caller grants allow "add"; the manifest only grants "secret". The gateway
    # must use the manifest grants and deny, not the caller's grants.
    app = build_tool_gateway_app(
        _gateway(),
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="secret")]),
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body("add", grants=("add",)), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "tool_denied"}


def test_tool_gateway_uses_manifest_grants():
    app = build_tool_gateway_app(
        _gateway(),
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="add")]),
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body("add"), headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"output": 3, "data_classes": ["internal"]}


def test_tool_gateway_fails_closed_without_resolver():
    app = build_tool_gateway_app(_gateway(), auth_token="secret")
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body("add"), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "grant_unavailable"}
