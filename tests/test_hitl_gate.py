"""SLICE-180: the tool approval gate is driven by risk_level (ADR-0031 slice 3)."""

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
from adk_agent.tools.catalog import ToolEntry
from adk_agent.tools.service import build_tool_gateway_app

AUTH = {"Authorization": "Bearer secret"}


def _spec(**overrides) -> ToolSpec:
    return ToolSpec(tool_id="write", handler=lambda **kwargs: {"ok": True}, **overrides)


def test_l3_tool_requires_approval():
    assert _spec(risk_level="L3").needs_approval is True


def test_l4_tool_requires_approval():
    assert _spec(risk_level="L4").needs_approval is True


def test_l2_tool_no_approval_without_flag():
    assert _spec(risk_level="L2").needs_approval is False


def test_requires_approval_flag_still_wins():
    assert _spec(requires_approval=True).needs_approval is True
    entry = ToolEntry(tool_id="write", source="function", risk_level="L3")
    assert entry.needs_approval is True


def _resolver(grants):
    async def resolve(_invocation):
        return grants

    return resolve


def test_gateway_requires_approval_for_l3_tool():
    registry = FunctionRegistry(
        [ToolSpec(tool_id="write", handler=lambda **kwargs: {"ok": True}, risk_level="L3")]
    )
    gateway = FunctionToolGateway(registry)
    app = build_tool_gateway_app(
        gateway,
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="write")]),
    )
    body = ToolGatewayRequest(
        invocation=Invocation(
            run_id="r1",
            trace_id="tr1",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
            input="hi",
        ),
        request=ToolRequest(tool_id="write", args={}, idempotency_key="k1"),
        grants=[ToolGrant(tool_id="write")],
    )
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=body.model_dump(mode="json"), headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "tool_denied"}
