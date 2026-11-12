"""SLICE-047: the HTTP gateway clients propagate the trace id."""

from __future__ import annotations

import asyncio
from typing import Any

from adk_agent.core import (
    AgentRef,
    Invocation,
    Message,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
    ToolGrant,
    ToolRequest,
    ToolResponse,
)
from adk_agent.models.http_gateway import HttpModelGateway
from adk_agent.tools import GrantPolicyEngine
from adk_agent.tools.http_gateway import HttpToolGateway


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.headers: dict[str, str] | None = None

    async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
        self.headers = headers
        return FakeResponse(self.payload)


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def test_model_gateway_sends_trace_header():
    payload = ModelResponse(
        text="ok", provider="fake", model="m", input_tokens=1, output_tokens=1, egress="none"
    ).model_dump(mode="json")
    client = FakeClient(payload)
    gateway = HttpModelGateway("http://gateway", auth_token="secret", client=client)

    asyncio.run(
        gateway.complete(
            _invocation(),
            ModelRequest(provider="fake", model="m", messages=[Message(role="user", content="hi")]),
            ModelPolicy(provider_allowlist=["fake"]),
        )
    )

    assert client.headers is not None
    assert client.headers["X-Trace-Id"] == "tr1"
    assert client.headers["Authorization"] == "Bearer secret"


def test_tool_gateway_sends_trace_header():
    payload = ToolResponse(output=3).model_dump(mode="json")
    client = FakeClient(payload)
    gateway = HttpToolGateway("http://gateway", client=client)

    asyncio.run(
        gateway.invoke(
            _invocation(),
            ToolRequest(tool_id="add", args={"a": 1, "b": 2}),
            GrantPolicyEngine([ToolGrant(tool_id="add")]),
        )
    )

    assert client.headers is not None
    assert client.headers["X-Trace-Id"] == "tr1"
    assert "Authorization" not in client.headers


def test_model_gateway_without_token_still_sends_trace_header():
    payload = ModelResponse(
        text="ok", provider="fake", model="m", input_tokens=1, output_tokens=1, egress="none"
    ).model_dump(mode="json")
    client = FakeClient(payload)
    gateway = HttpModelGateway("http://gateway", client=client)

    asyncio.run(
        gateway.complete(
            _invocation(),
            ModelRequest(provider="fake", model="m", messages=[Message(role="user", content="hi")]),
            ModelPolicy(provider_allowlist=["fake"]),
        )
    )

    assert client.headers == {"X-Trace-Id": "tr1"}
