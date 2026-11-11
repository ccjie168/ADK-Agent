"""SLICE-022: the tool gateway runs handlers inside the sandbox."""

from __future__ import annotations

import asyncio
import socket
import time

import pytest

from adk_agent.core import AgentRef, Invocation, Principal, ToolGrant, ToolRequest
from adk_agent.sandbox import SandboxPolicy, SandboxTimeout, SandboxToolError, ToolSandbox
from adk_agent.tools import FunctionRegistry, FunctionToolGateway, GrantPolicyEngine, ToolSpec


def sandbox_add(a: int, b: int) -> int:
    return a + b


def sandbox_sleep() -> str:
    time.sleep(2)
    return "done"


def sandbox_fetch() -> str:
    with socket.create_connection(("example.com", 80), timeout=2):
        return "connected"


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
        agent_ref=AgentRef(id="sandbox-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _gateway(handler, audit, **policy) -> FunctionToolGateway:
    spec = ToolSpec("tool", handler)
    return FunctionToolGateway(
        FunctionRegistry([spec]),
        audit=audit,
        sandbox=ToolSandbox(SandboxPolicy(**policy)),
    )


def test_gateway_result_is_audited():
    audit = FakeAudit()
    gateway = _gateway(sandbox_add, audit, timeout_seconds=10.0)
    response = asyncio.run(
        gateway.invoke(
            _invocation(),
            ToolRequest(tool_id="tool", args={"a": 1, "b": 2}),
            GrantPolicyEngine([ToolGrant(tool_id="tool")]),
        )
    )
    assert response.output == 3
    [event] = audit.events
    assert event.status == "ok"
    assert event.result_hash


def test_gateway_timeout_is_audited():
    audit = FakeAudit()
    gateway = _gateway(sandbox_sleep, audit, timeout_seconds=0.2)
    with pytest.raises(SandboxTimeout):
        asyncio.run(
            gateway.invoke(
                _invocation(),
                ToolRequest(tool_id="tool"),
                GrantPolicyEngine([ToolGrant(tool_id="tool")]),
            )
        )
    [event] = audit.events
    assert event.status == "error"
    assert event.error_code == "SandboxTimeout"


def test_gateway_network_denial_is_audited():
    audit = FakeAudit()
    gateway = _gateway(sandbox_fetch, audit, timeout_seconds=10.0)
    with pytest.raises(SandboxToolError) as raised:
        asyncio.run(
            gateway.invoke(
                _invocation(),
                ToolRequest(tool_id="tool"),
                GrantPolicyEngine([ToolGrant(tool_id="tool")]),
            )
        )
    assert raised.value.error_code == "SandboxViolation"
    [event] = audit.events
    assert event.status == "error"
    assert event.error_code == "SandboxViolation"
