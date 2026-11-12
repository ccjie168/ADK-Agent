"""SLICE-033: the HTTP tool gateway client."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adk_agent.core import (
    AgentRef,
    Invocation,
    PolicyDecision,
    Principal,
    ToolGrant,
    ToolRequest,
)
from adk_agent.tools import (
    FunctionRegistry,
    FunctionToolGateway,
    GrantPolicyEngine,
    ToolDenied,
    ToolSpec,
)
from adk_agent.tools.http_gateway import HttpToolGateway, ToolGatewayError
from adk_agent.tools.service import build_tool_gateway_app


def add(a: int, b: int) -> int:
    return a + b


class OpaquePolicy:
    async def decide(self, invocation, action: str, target: str) -> PolicyDecision:
        return PolicyDecision(decision="allow", reason="opaque", policy_version="v1")


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _client(*, auth_token: str = "secret") -> tuple[HttpToolGateway, httpx.AsyncClient]:
    registry = FunctionRegistry([ToolSpec(tool_id="add", handler=add)])
    app = build_tool_gateway_app(FunctionToolGateway(registry), auth_token="secret")
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    )
    return HttpToolGateway("http://gateway", auth_token=auth_token, client=http_client), http_client


def _invoke(client: HttpToolGateway, policy=None):
    return asyncio.run(
        client.invoke(
            _invocation(),
            ToolRequest(tool_id="add", args={"a": 1, "b": 2}),
            policy or GrantPolicyEngine([ToolGrant(tool_id="add")]),
        )
    )


def test_client_roundtrip():
    client, http_client = _client()
    try:
        response = _invoke(client)
    finally:
        asyncio.run(http_client.aclose())
    assert response.output == 3


def test_client_maps_denial():
    client, http_client = _client()
    try:
        with pytest.raises(ToolDenied):
            _invoke(client, GrantPolicyEngine([]))
    finally:
        asyncio.run(http_client.aclose())


def test_client_rejects_bad_token():
    client, http_client = _client(auth_token="wrong")
    try:
        with pytest.raises(ToolGatewayError):
            _invoke(client)
    finally:
        asyncio.run(http_client.aclose())


def test_client_rejects_opaque_policy():
    client, http_client = _client()
    try:
        with pytest.raises(ToolGatewayError):
            _invoke(client, OpaquePolicy())
    finally:
        asyncio.run(http_client.aclose())


def test_load_tools_accepts_callables_and_specs(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text(
        "from adk_agent.tools import ToolSpec\n"
        "\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def write():\n"
        "    return 'ok'\n"
        "\n"
        "tools = {\n"
        "    'add': add,\n"
        "    'write': ToolSpec(tool_id='write', handler=write, requires_approval=True),\n"
        "}\n",
        encoding="utf-8",
    )

    from adk_agent.cli import _load_tools

    registry = _load_tools(str(path))
    assert {spec.tool_id for spec in registry.specs()} == {"add", "write"}
    assert registry.get("write").requires_approval is True


def test_load_tools_rejects_missing_mapping(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("x = 1\n", encoding="utf-8")

    from adk_agent.cli import _load_tools

    with pytest.raises(SystemExit):
        _load_tools(str(path))
