"""SLICE-137: the tool gateway client."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adk_agent.core import AgentRef, Invocation, Principal
from adk_agent.tools.client import ToolDenied, ToolGatewayClient, ToolGatewayError


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="t1",
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _client(handler) -> ToolGatewayClient:
    transport = httpx.MockTransport(handler)
    return ToolGatewayClient(
        "http://gateway", token="secret", client=httpx.AsyncClient(transport=transport)
    )


def test_invoke_returns_output():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        body = request.read().decode()
        assert '"tool_id":"crm.read"' in body
        return httpx.Response(200, json={"output": {"ok": 1}, "data_classes": []})

    result = asyncio.run(_client(handler).invoke(_invocation(), "crm.read", {"x": 1}))

    assert result == {"ok": 1}


def test_denied_maps_to_tool_denied():
    client = _client(lambda request: httpx.Response(403, json={"error": "tool_denied"}))

    with pytest.raises(ToolDenied):
        asyncio.run(client.invoke(_invocation(), "crm.read", {}))


def test_server_error_maps_to_gateway_error():
    client = _client(lambda request: httpx.Response(502, json={"error": "tool_call_failed"}))

    with pytest.raises(ToolGatewayError):
        asyncio.run(client.invoke(_invocation(), "crm.read", {}))


def test_unreachable_gateway_maps_to_gateway_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    client = _client(handler)

    with pytest.raises(ToolGatewayError):
        asyncio.run(client.invoke(_invocation(), "crm.read", {}))


def test_redirect_is_refused():
    client = _client(
        lambda request: httpx.Response(302, headers={"location": "http://elsewhere/invoke"})
    )

    with pytest.raises(ToolGatewayError):
        asyncio.run(client.invoke(_invocation(), "crm.read", {}))


def test_missing_token_is_a_gateway_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(401, json={"error": "unauthorized"})

    transport = httpx.MockTransport(handler)
    client = ToolGatewayClient("http://gateway", client=httpx.AsyncClient(transport=transport))

    with pytest.raises(ToolGatewayError):
        asyncio.run(client.invoke(_invocation(), "crm.read", {}))
