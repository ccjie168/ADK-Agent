"""SLICE-026: a supervisor agent picks workers until it says done."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
    SupervisorDecision,
)
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    BudgetExceeded,
    PlanDenied,
    PlanExecutor,
    SupervisorLimit,
    SupervisorProtocolError,
)

_DIGEST = "d" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class Scripted:
    def __init__(self, texts: list[str], cost: float = 0.0) -> None:
        self.texts = list(texts)
        self.cost = cost
        self.calls: list[Invocation] = []

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=text,
            cost_usd=self.cost,
        )


class Recorder:
    def __init__(self, cost: float = 0.0) -> None:
        self.cost = cost
        self.calls: list[Invocation] = []

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{invocation.agent_ref.id}:{invocation.input}",
            cost_usd=self.cost,
        )


def _ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent(text: str = "root", **overrides) -> Invocation:
    data = {
        "run_id": "parent-run",
        "trace_id": "trace-1",
        "principal": Principal(tenant="t1", subject="alice", kind="human"),
        "agent_ref": _ref("flow"),
        "input": text,
    }
    data.update(overrides)
    return Invocation(**data)


def _step(step_id: str, **overrides) -> PlanStep:
    data = {"id": step_id, "agent_ref": _ref(step_id)}
    data.update(overrides)
    return PlanStep(**data)


def _plan(
    steps: list[PlanStep],
    supervisor: AgentRef | None = None,
    max_rounds: int = 3,
) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="supervisor",
        supervisor=supervisor or _ref("boss"),
        max_rounds=max_rounds,
        steps=steps,
    )


def _executor(
    agents: dict[str, Any],
    allowed: list[str],
    audit: FakeAudit | None = None,
) -> PlanExecutor:
    return PlanExecutor(
        agents,
        policy=AgentGrantPolicyEngine(allowed),
        audit=audit,
    )


def _call(worker: str, text: str) -> str:
    return json.dumps({"action": "call", "worker": worker, "input": text})


def _done(text: str = "") -> str:
    return json.dumps({"action": "done", "final": text})


def test_supervisor_calls_worker_then_done():
    audit = FakeAudit()
    boss = Scripted([_call("a", "do it"), _done("finished")])
    worker = Recorder()
    plan = _plan([_step("a")])

    result = asyncio.run(
        _executor({"boss": boss, "a": worker}, ["boss", "a"], audit).run(plan, _parent())
    )

    assert result.final_text == "finished"
    assert result.outputs == {"a#1": "out:a:do it"}
    assert len(boss.calls) == 2
    assert len(worker.calls) == 1
    assert "History:" in boss.calls[1].input
    assert "out:a:do it" in boss.calls[1].input

    actions = [event.action for event in audit.events]
    assert actions.count("orchestration.supervisor") == 2
    assert actions.count("orchestration.step") == 1
    assert actions.count("orchestration.run") == 1
    supervisor_events = [
        event for event in audit.events if event.action == "orchestration.supervisor"
    ]
    assert [event.target for event in supervisor_events] == ["round:1", "round:2"]
    assert {event.trace_id for event in audit.events} == {"trace-1"}


def test_supervisor_done_immediately():
    boss = Scripted([_done("ok")])
    worker = Recorder()
    plan = _plan([_step("a")])

    result = asyncio.run(_executor({"boss": boss, "a": worker}, ["boss", "a"]).run(plan, _parent()))

    assert result.final_text == "ok"
    assert result.outputs == {}
    assert worker.calls == []


def test_supervisor_done_empty_final_uses_last_output():
    boss = Scripted([_call("a", "do it"), _done("")])
    worker = Recorder()
    plan = _plan([_step("a")])

    result = asyncio.run(_executor({"boss": boss, "a": worker}, ["boss", "a"]).run(plan, _parent()))

    assert result.final_text == "out:a:do it"


def test_supervisor_unknown_worker():
    audit = FakeAudit()
    boss = Scripted([_call("missing", "x")])
    worker = Recorder()
    plan = _plan([_step("a")])

    with pytest.raises(SupervisorProtocolError):
        asyncio.run(
            _executor({"boss": boss, "a": worker}, ["boss", "a"], audit).run(plan, _parent())
        )

    assert worker.calls == []
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "supervisor_protocol"


def test_supervisor_invalid_json():
    audit = FakeAudit()
    boss = Scripted(["not json"])
    plan = _plan([_step("a")])

    with pytest.raises(SupervisorProtocolError):
        asyncio.run(
            _executor({"boss": boss, "a": Recorder()}, ["boss", "a"], audit).run(plan, _parent())
        )

    supervisor_events = [
        event for event in audit.events if event.action == "orchestration.supervisor"
    ]
    assert supervisor_events[-1].status == "error"
    assert supervisor_events[-1].error_code == "supervisor_protocol"


def test_supervisor_round_limit():
    audit = FakeAudit()
    boss = Scripted([_call("a", "again")])
    worker = Recorder()
    plan = _plan([_step("a")], max_rounds=2)

    with pytest.raises(SupervisorLimit):
        asyncio.run(
            _executor({"boss": boss, "a": worker}, ["boss", "a"], audit).run(plan, _parent())
        )

    assert len(worker.calls) == 2
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "round_limit"


def test_supervisor_policy_denied():
    audit = FakeAudit()
    boss = Scripted([_done("ok")])
    plan = _plan([_step("a")])

    with pytest.raises(PlanDenied):
        asyncio.run(_executor({"boss": boss, "a": Recorder()}, ["a"], audit).run(plan, _parent()))

    assert boss.calls == []
    supervisor_events = [
        event for event in audit.events if event.action == "orchestration.supervisor"
    ]
    assert supervisor_events[-1].status == "denied"
    assert supervisor_events[-1].error_code == "policy_denied"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "denied"


def test_supervisor_budget():
    audit = FakeAudit()
    boss = Scripted([_call("a", "costly"), _done("done")])
    worker = Recorder(cost=2.0)
    plan = _plan([_step("a")])

    with pytest.raises(BudgetExceeded):
        asyncio.run(
            _executor({"boss": boss, "a": worker}, ["boss", "a"], audit).run(
                plan, _parent(budget_usd=1.0)
            )
        )

    assert len(worker.calls) == 1
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "denied"
    assert runs[-1].error_code == "budget_exceeded"


def test_supervisor_validation():
    with pytest.raises(ValidationError):
        OrchestrationPlan(
            plan_id="flow",
            version="1.0.0",
            strategy="supervisor",
            steps=[_step("a")],
        )
    with pytest.raises(ValidationError):
        OrchestrationPlan(
            plan_id="flow",
            version="1.0.0",
            strategy="sequential",
            supervisor=_ref("boss"),
            steps=[_step("a")],
        )
    with pytest.raises(ValidationError):
        _plan([_step("a", depends_on=["b"]), _step("b")])
    with pytest.raises(ValidationError):
        _plan([_step("boss")], supervisor=_ref("boss"))
    with pytest.raises(ValidationError):
        SupervisorDecision(action="done", worker="a")
    with pytest.raises(ValidationError):
        SupervisorDecision(action="call")
