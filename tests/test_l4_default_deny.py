"""SLICE-170: L4 grants are denied by default at the authorization decision point."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from adk_agent.core import (
    AgentRef,
    Invocation,
    Principal,
    ToolGatewayRequest,
    ToolGrant,
    ToolRequest,
)
from adk_agent.tools import FunctionRegistry, FunctionToolGateway, GrantPolicyEngine, ToolSpec
from adk_agent.tools.service import build_tool_gateway_app

AUTH = {"Authorization": "Bearer secret"}


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _decide(grants: list[ToolGrant], tool_id: str):
    return asyncio.run(GrantPolicyEngine(grants).decide(_invocation(), "tool.call", tool_id))


def test_l4_grant_is_denied_by_default():
    decision = _decide([ToolGrant(tool_id="write", risk_level="L4")], "write")
    assert decision.decision == "deny"
    assert decision.error_code == "l4_default_deny"


def test_l3_grant_is_allowed():
    assert _decide([ToolGrant(tool_id="write", risk_level="L3")], "write").decision == "allow"


def test_non_l4_grant_is_allowed():
    for level in ("L1", "L2", None):
        decision = _decide([ToolGrant(tool_id="write", risk_level=level)], "write")
        assert decision.decision == "allow", level


def test_l4_wins_over_lower_risk():
    grants = [
        ToolGrant(tool_id="write", risk_level="L1"),
        ToolGrant(tool_id="write", risk_level="L4"),
    ]
    decision = _decide(grants, "write")
    assert decision.decision == "deny"
    assert decision.error_code == "l4_default_deny"


def add(a: int, b: int) -> int:
    return a + b


def _resolver(grants):
    async def resolve(_invocation):
        return grants

    return resolve


def test_gateway_denies_l4_tool():
    registry = FunctionRegistry([ToolSpec(tool_id="add", handler=add, data_classes=("internal",))])
    gateway = FunctionToolGateway(registry)
    app = build_tool_gateway_app(
        gateway,
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="add", risk_level="L4")]),
    )
    body = ToolGatewayRequest(
        invocation=_invocation(),
        request=ToolRequest(tool_id="add", args={"a": 1, "b": 2}),
        grants=[ToolGrant(tool_id="add", risk_level="L4")],
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=body.model_dump(mode="json"), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "tool_denied"}
