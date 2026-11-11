"""SLICE-019: grant-based tool policy."""

from __future__ import annotations

import asyncio

from adk_agent.core import AgentRef, Invocation, Principal, ToolGrant
from adk_agent.tools import GrantPolicyEngine


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def test_granted_tool_is_allowed():
    engine = GrantPolicyEngine([ToolGrant(tool_id="add")])
    decision = asyncio.run(engine.decide(_invocation(), "tool.call", "add"))
    assert decision.decision == "allow"


def test_other_tool_is_denied():
    engine = GrantPolicyEngine([ToolGrant(tool_id="add")])
    decision = asyncio.run(engine.decide(_invocation(), "tool.call", "delete"))
    assert decision.decision == "deny"
