"""SLICE-019: the tool gateway enforces grants and audits calls."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import AgentRef, Invocation, Principal, ToolGrant, ToolRequest
from adk_agent.tools import (
    FunctionRegistry,
    FunctionToolGateway,
    GrantPolicyEngine,
    ToolDenied,
    ToolSpec,
)


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _policy(tool_id: str = "add") -> GrantPolicyEngine:
    return GrantPolicyEngine([ToolGrant(tool_id=tool_id)])


def _gateway(specs, audit=None) -> FunctionToolGateway:
    return FunctionToolGateway(FunctionRegistry(specs), audit=audit)


def _request(tool_id: str = "add", **args) -> ToolRequest:
    return ToolRequest(tool_id=tool_id, args=args)


def test_allowed_tool_is_audited():
    def add(a, b):
        return a + b

    audit = FakeAudit()
    gateway = _gateway([ToolSpec("add", add, ("internal",))], audit=audit)

    response = asyncio.run(gateway.invoke(_invocation(), _request(a=1, b=2), _policy()))

    assert response.output == 3
    assert response.data_classes == ["internal"]
    [event] = audit.events
    assert event.action == "tool.call"
    assert event.target == "add"
    assert event.status == "ok"
    assert event.data_classes == ["internal"]
    assert event.args_hash
    assert event.result_hash
    assert event.egress == "none"


def test_denied_tool_is_not_called():
    called: list = []

    def add(a, b):
        called.append(True)
        return a + b

    audit = FakeAudit()
    gateway = _gateway([ToolSpec("add", add)], audit=audit)

    with pytest.raises(ToolDenied):
        asyncio.run(gateway.invoke(_invocation(), _request(a=1, b=2), _policy("other")))

    assert called == []
    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "policy_denied"


def test_unknown_tool_is_denied():
    audit = FakeAudit()
    gateway = _gateway([], audit=audit)

    with pytest.raises(ToolDenied):
        asyncio.run(gateway.invoke(_invocation(), _request(), _policy()))

    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "tool_unavailable"


def test_handler_error_is_audited():
    def boom():
        raise RuntimeError("boom")

    audit = FakeAudit()
    gateway = _gateway([ToolSpec("boom", boom)], audit=audit)

    with pytest.raises(RuntimeError):
        asyncio.run(gateway.invoke(_invocation(), _request("boom"), _policy("boom")))

    [event] = audit.events
    assert event.status == "error"
    assert event.error_code == "RuntimeError"


def test_requires_approval_is_denied():
    called: list = []

    def add(a, b):
        called.append(True)
        return a + b

    audit = FakeAudit()
    gateway = _gateway([ToolSpec("add", add, requires_approval=True)], audit=audit)

    with pytest.raises(ToolDenied):
        asyncio.run(gateway.invoke(_invocation(), _request(a=1, b=2), _policy()))

    assert called == []
    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "approval_required"


def test_async_handler():
    async def add(a, b):
        return a + b

    gateway = _gateway([ToolSpec("add", add)])
    response = asyncio.run(gateway.invoke(_invocation(), _request(a=1, b=2), _policy()))
    assert response.output == 3


def test_duplicate_tool_ids_rejected():
    def add(a, b):
        return a + b

    with pytest.raises(ValueError):
        FunctionRegistry([ToolSpec("add", add), ToolSpec("add", add)])
