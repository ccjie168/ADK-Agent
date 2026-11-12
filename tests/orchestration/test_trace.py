"""SLICE-027: build a replayable trace tree from audit events."""

from __future__ import annotations

import asyncio
import json

import pytest

from adk_agent.audit import ListAuditSink
from adk_agent.core import (
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
)
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    PlanExecutionError,
    PlanExecutor,
    build_trace,
)

_DIGEST = "d" * 64


class Recorder:
    def __init__(self, cost: float = 0.2) -> None:
        self.cost = cost
        self.calls: list[Invocation] = []

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{invocation.agent_ref.id}",
            cost_usd=self.cost,
        )


class Boss:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=text,
        )


def _ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent() -> Invocation:
    return Invocation(
        run_id="parent-run",
        trace_id="trace-1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=_ref("flow"),
        input="root",
    )


def _step(step_id: str, **overrides) -> PlanStep:
    data = {"id": step_id, "agent_ref": _ref(step_id)}
    data.update(overrides)
    return PlanStep(**data)


def _run(plan: OrchestrationPlan, agents: dict) -> ListAuditSink:
    audit = ListAuditSink()
    executor = PlanExecutor(agents, policy=AgentGrantPolicyEngine(list(agents)), audit=audit)
    asyncio.run(executor.run(plan, _parent()))
    return audit


def test_trace_has_plan_and_steps():
    recorder = Recorder()
    plan = OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="sequential",
        steps=[_step("a"), _step("b", depends_on=["a"])],
    )
    audit = _run(plan, {"a": recorder, "b": recorder})

    trace = build_trace(audit.recent(), "trace-1")

    assert trace.kind == "plan"
    assert trace.id == "flow@1.0.0"
    assert trace.status == "ok"
    assert [child.id for child in trace.children] == ["a", "b"]
    assert all(child.kind == "step" for child in trace.children)
    assert [child.cost_usd for child in trace.children] == [0.2, 0.2]
    assert trace.cost_usd == 0.4
    assert trace.latency_ms is not None


def test_trace_marks_errors():
    async def boom(invocation: Invocation) -> InvocationResult:
        raise RuntimeError("boom")

    plan = OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="single",
        steps=[_step("a")],
    )
    audit = ListAuditSink()
    executor = PlanExecutor({"a": boom}, policy=AgentGrantPolicyEngine(["a"]), audit=audit)
    with pytest.raises(PlanExecutionError):
        asyncio.run(executor.run(plan, _parent()))

    trace = build_trace(audit.recent(), "trace-1")

    assert trace.status == "error"
    assert trace.error_code == "RuntimeError"
    assert trace.children[0].status == "error"
    assert trace.children[0].error_code == "RuntimeError"


def test_trace_nests_supervisor_rounds():
    boss = Boss(
        [
            json.dumps({"action": "call", "worker": "a", "input": "do it"}),
            json.dumps({"action": "done", "final": "finished"}),
        ]
    )
    recorder = Recorder()
    plan = OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="supervisor",
        supervisor=_ref("boss"),
        max_rounds=3,
        steps=[_step("a")],
    )
    audit = ListAuditSink()
    executor = PlanExecutor(
        {"boss": boss, "a": recorder},
        policy=AgentGrantPolicyEngine(["boss", "a"]),
        audit=audit,
    )
    asyncio.run(executor.run(plan, _parent()))

    trace = build_trace(audit.recent(), "trace-1")

    assert trace.status == "ok"
    assert trace.children[0].kind == "supervisor"
    assert trace.children[0].id == "round:1"
    assert trace.children[0].children[0].kind == "step"
    assert trace.children[0].children[0].id == "a"


def test_trace_not_found():
    trace = build_trace([], "missing")

    assert trace.kind == "plan"
    assert trace.status == "error"
    assert trace.error_code == "trace_not_found"
