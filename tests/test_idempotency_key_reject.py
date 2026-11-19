"""SLICE-172: write tools require an idempotency key (ADR-0034 slice 2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

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


def _gateway(write: bool) -> FunctionToolGateway:
    registry = FunctionRegistry(
        [ToolSpec(tool_id="add", handler=add, data_classes=("internal",), write=write)]
    )
    return FunctionToolGateway(registry)


def _resolver(grants):
    async def resolve(_invocation):
        return grants

    return resolve


def _body(idempotency_key: str | None = None) -> dict:
    request = ToolGatewayRequest(
        invocation=Invocation(
            run_id="r1",
            trace_id="tr1",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
            input="hi",
        ),
        request=ToolRequest(tool_id="add", args={"a": 1, "b": 2}, idempotency_key=idempotency_key),
        grants=[ToolGrant(tool_id="add")],
    )
    return request.model_dump(mode="json")


def test_tool_request_accepts_idempotency_key():
    assert ToolRequest(tool_id="x", idempotency_key="k1").idempotency_key == "k1"


def test_tool_request_rejects_empty_idempotency_key():
    with pytest.raises(ValidationError):
        ToolRequest(tool_id="x", idempotency_key="")


def test_gateway_rejects_missing_idempotency_key():
    app = build_tool_gateway_app(
        _gateway(write=True),
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="add")]),
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body(), headers=AUTH)
    assert response.status_code == 400
    assert response.json() == {"error": "idempotency_missing"}


def test_gateway_allows_read_tool_without_key():
    app = build_tool_gateway_app(
        _gateway(write=False),
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="add")]),
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body(), headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"output": 3, "data_classes": ["internal"]}


def test_gateway_allows_write_tool_with_key():
    app = build_tool_gateway_app(
        _gateway(write=True),
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="add")]),
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_body(idempotency_key="k1"), headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"output": 3, "data_classes": ["internal"]}
