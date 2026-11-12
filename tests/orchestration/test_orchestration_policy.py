"""SLICE-023: agent invocation grants gate the orchestrator."""

from __future__ import annotations

import asyncio

from adk_agent.core import AgentRef, Invocation, Principal
from adk_agent.orchestration import AgentGrantPolicyEngine


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="flow", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def test_granted_agent_is_allowed():
    engine = AgentGrantPolicyEngine(["worker"])
    decision = asyncio.run(engine.decide(_invocation(), "agent.invoke", "worker"))
    assert decision.decision == "allow"


def test_other_agent_is_denied():
    engine = AgentGrantPolicyEngine(["worker"])
    decision = asyncio.run(engine.decide(_invocation(), "agent.invoke", "other"))
    assert decision.decision == "deny"


def test_non_agent_action_is_denied():
    engine = AgentGrantPolicyEngine(["worker"])
    decision = asyncio.run(engine.decide(_invocation(), "tool.call", "worker"))
    assert decision.decision == "deny"
