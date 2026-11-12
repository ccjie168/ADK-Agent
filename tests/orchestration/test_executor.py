"""SLICE-023: the plan executor runs single and sequential plans."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from adk_agent.audit.hashing import hash_text
from adk_agent.core import (
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
    plan_digest,
)
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    PlanDenied,
    PlanExecutionError,
    PlanExecutor,
    UnknownAgent,
)

_DIGEST = "d" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class Recorder:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.calls: list[Invocation] = []
        self.responses = responses or {}

    async def call(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        text = self.responses.get(invocation.agent_ref.id, f"out:{invocation.input}")
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=text,
        )


def _ref(name: str = "worker") -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent(**overrides) -> Invocation:
    data = {
        "run_id": "parent-run",
        "trace_id": "trace-1",
        "principal": Principal(tenant="t1", subject="alice", kind="human"),
        "agent_ref": _ref("flow"),
        "input": "root input",
    }
    data.update(overrides)
    return Invocation(**data)


def _step(step_id: str, agent: str = "worker", **overrides) -> PlanStep:
    data = {"id": step_id, "agent_ref": _ref(agent)}
    data.update(overrides)
    return PlanStep(**data)


def _plan(steps, strategy: str = "sequential") -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy=strategy,
        steps=steps,
    )


def _executor(recorder: Recorder, agents: list[str], audit: FakeAudit | None = None):
    return PlanExecutor(
        {name: recorder.call for name in agents},
        policy=AgentGrantPolicyEngine(agents),
        audit=audit,
    )


def test_single_plan_uses_parent_input():
    recorder = Recorder()
    plan = _plan([_step("a")], strategy="single")

    result = asyncio.run(_executor(recorder, ["worker"]).run(plan, _parent()))

    assert [call.input for call in recorder.calls] == ["root input"]
    assert result.outputs == {"a": "out:root input"}
    assert result.final_text == "out:root input"
    assert result.run_id == "parent-run"
    assert result.trace_id == "trace-1"


def test_sequential_plan_composes_inputs():
    recorder = Recorder()
    plan = _plan(
        [
            _step("a", input="start"),
            _step("b", depends_on=["a"], inputs_from=["a"], input="next"),
        ]
    )

    result = asyncio.run(_executor(recorder, ["worker"]).run(plan, _parent()))

    assert [call.input for call in recorder.calls] == [
        "start",
        "next\n\nout:start",
    ]
    assert result.outputs == {
        "a": "out:start",
        "b": "out:next\n\nout:start",
    }
    assert result.final_text == "out:next\n\nout:start"


def test_denied_agent_is_not_called():
    audit = FakeAudit()
    recorder = Recorder()
    plan = _plan(
        [
            _step("a", agent="worker"),
            _step("b", agent="other", depends_on=["a"]),
        ]
    )

    with pytest.raises(PlanDenied):
        asyncio.run(_executor(recorder, ["worker"], audit).run(plan, _parent()))

    assert [call.agent_ref.id for call in recorder.calls] == ["worker"]
    step_events = [event for event in audit.events if event.action == "orchestration.step"]
    assert [event.status for event in step_events] == ["ok", "denied"]
    assert step_events[1].error_code == "policy_denied"
    run_events = [event for event in audit.events if event.action == "orchestration.run"]
    assert run_events[-1].status == "denied"


def test_unknown_agent_fails():
    audit = FakeAudit()
    recorder = Recorder()
    plan = _plan([_step("a", agent="missing")], strategy="single")
    executor = PlanExecutor(
        {},
        policy=AgentGrantPolicyEngine(["missing"]),
        audit=audit,
    )

    with pytest.raises(UnknownAgent):
        asyncio.run(executor.run(plan, _parent()))

    assert recorder.calls == []
    run_events = [event for event in audit.events if event.action == "orchestration.run"]
    assert run_events[-1].status == "error"
    assert run_events[-1].error_code == "unknown_agent"


def test_step_error_is_audited():
    async def boom(invocation: Invocation) -> InvocationResult:
        raise RuntimeError("boom")

    audit = FakeAudit()
    plan = _plan([_step("a")], strategy="single")
    executor = PlanExecutor(
        {"worker": boom},
        policy=AgentGrantPolicyEngine(["worker"]),
        audit=audit,
    )

    with pytest.raises(PlanExecutionError) as raised:
        asyncio.run(executor.run(plan, _parent()))
    assert raised.value.step_id == "a"

    step_events = [event for event in audit.events if event.action == "orchestration.step"]
    assert step_events[-1].status == "error"
    assert step_events[-1].error_code == "RuntimeError"
    run_events = [event for event in audit.events if event.action == "orchestration.run"]
    assert run_events[-1].status == "error"
    assert run_events[-1].error_code == "RuntimeError"


def test_audit_shares_trace_id():
    audit = FakeAudit()
    recorder = Recorder()
    plan = _plan([_step("a"), _step("b", depends_on=["a"])])

    asyncio.run(_executor(recorder, ["worker"], audit).run(plan, _parent()))

    assert {event.trace_id for event in audit.events} == {"trace-1"}
    step_events = [event for event in audit.events if event.action == "orchestration.step"]
    assert {event.run_id for event in step_events} != {"parent-run"}
    assert {call.trace_id for call in recorder.calls} == {"trace-1"}
    assert {call.run_id for call in recorder.calls}.isdisjoint({"parent-run"})


def test_child_invocation_shape():
    recorder = Recorder()
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
    plan = _plan(
        [
            _step(
                "a",
                timeout_seconds=10,
                budget_usd=0.25,
            )
        ],
        strategy="single",
    )
    parent = _parent(deadline=deadline, budget_usd=1.0)

    asyncio.run(_executor(recorder, ["worker"]).run(plan, parent))

    [child] = recorder.calls
    assert child.agent_ref == plan.steps[0].agent_ref
    assert child.run_id != parent.run_id
    assert child.trace_id == parent.trace_id
    assert child.principal == parent.principal
    assert child.budget_usd == 0.25
    assert child.deadline is not None
    assert child.deadline < deadline


def test_plan_audit_has_digest():
    audit = FakeAudit()
    recorder = Recorder()
    plan = _plan([_step("a")], strategy="single")

    asyncio.run(_executor(recorder, ["worker"], audit).run(plan, _parent()))

    [event] = [event for event in audit.events if event.action == "orchestration.run"]
    assert event.agent_ref.digest == plan_digest(plan)
    assert event.args_hash == hash_text("root input")
    assert event.result_hash == hash_text("out:root input")
