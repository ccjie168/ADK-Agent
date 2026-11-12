"""SLICE-024: retries, timeouts, budgets, and cancellation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

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
    BudgetExceeded,
    CancellationToken,
    PlanCancelled,
    PlanExecutionError,
    PlanExecutor,
    PlanTimeout,
    StepTimeout,
)

_DIGEST = "d" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class ScriptedAgent:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[Invocation] = []

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return await outcome(invocation)
        cost, text = outcome
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=text,
            cost_usd=cost,
        )


async def _sleep_then_return(invocation: Invocation) -> InvocationResult:
    await asyncio.sleep(2)
    return InvocationResult(
        run_id=invocation.run_id,
        trace_id=invocation.trace_id,
        agent_ref=invocation.agent_ref,
        text="late",
    )


def _ref(name: str = "worker") -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent(**overrides) -> Invocation:
    data = {
        "run_id": "parent-run",
        "trace_id": "trace-1",
        "principal": Principal(tenant="t1", subject="alice", kind="human"),
        "agent_ref": _ref("flow"),
        "input": "root",
    }
    data.update(overrides)
    return Invocation(**data)


def _step(step_id: str = "a", **overrides) -> PlanStep:
    data = {"id": step_id, "agent_ref": _ref()}
    data.update(overrides)
    return PlanStep(**data)


def _plan(steps: list[PlanStep], strategy: str = "single") -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy=strategy,
        steps=steps,
    )


def _executor(agent: Any, audit: FakeAudit | None = None) -> PlanExecutor:
    return PlanExecutor(
        {"worker": agent},
        policy=AgentGrantPolicyEngine(["worker"]),
        audit=audit,
    )


def test_retry_until_success():
    audit = FakeAudit()
    agent = ScriptedAgent([RuntimeError("transient"), (0.0, "ok")])
    plan = _plan([_step(max_attempts=2)])

    result = asyncio.run(_executor(agent, audit).run(plan, _parent()))

    assert result.final_text == "ok"
    assert len(agent.calls) == 2
    retries = [event for event in audit.events if event.action == "orchestration.retry"]
    assert len(retries) == 1
    assert retries[0].error_code == "RuntimeError"
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert [event.status for event in steps] == ["ok"]


def test_retry_exhausted():
    audit = FakeAudit()
    agent = ScriptedAgent([RuntimeError("boom")])
    plan = _plan([_step(max_attempts=2)])

    with pytest.raises(PlanExecutionError) as raised:
        asyncio.run(_executor(agent, audit).run(plan, _parent()))

    assert raised.value.step_id == "a"
    assert len(agent.calls) == 2
    assert len([event for event in audit.events if event.action == "orchestration.retry"]) == 1
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].status == "error"
    assert steps[-1].error_code == "RuntimeError"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "error"
    assert runs[-1].error_code == "RuntimeError"


def test_timeout_is_retried_then_succeeds():
    audit = FakeAudit()
    agent = ScriptedAgent([_sleep_then_return, (0.0, "ok")])
    plan = _plan([_step(timeout_seconds=0.05, max_attempts=2)])

    result = asyncio.run(_executor(agent, audit).run(plan, _parent()))

    assert result.final_text == "ok"
    assert len(agent.calls) == 2
    retries = [event for event in audit.events if event.action == "orchestration.retry"]
    assert retries[0].error_code == "StepTimeout"


def test_step_timeout_exhausted():
    audit = FakeAudit()
    agent = ScriptedAgent([_sleep_then_return])
    plan = _plan([_step(timeout_seconds=0.05)])

    with pytest.raises(StepTimeout):
        asyncio.run(_executor(agent, audit).run(plan, _parent()))

    assert len(agent.calls) == 1
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "StepTimeout"


def test_plan_deadline_expired():
    audit = FakeAudit()
    agent = ScriptedAgent([(0.0, "ok")])
    parent = _parent(deadline=datetime.now(timezone.utc) - timedelta(seconds=1))

    with pytest.raises(PlanTimeout):
        asyncio.run(_executor(agent, audit).run(_plan([_step()]), parent))

    assert agent.calls == []
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "error"
    assert runs[-1].error_code == "plan_timeout"


def test_plan_deadline_limits_step_and_does_not_retry():
    audit = FakeAudit()
    agent = ScriptedAgent([_sleep_then_return])
    parent = _parent(deadline=datetime.now(timezone.utc) + timedelta(seconds=0.2))
    plan = _plan([_step(timeout_seconds=30, max_attempts=3)])

    with pytest.raises(PlanTimeout):
        asyncio.run(_executor(agent, audit).run(plan, parent))

    assert len(agent.calls) == 1
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "plan_timeout"


def test_budget_exceeded_after_step():
    audit = FakeAudit()
    agent = ScriptedAgent([(2.0, "costly")])
    parent = _parent(budget_usd=1.0)

    with pytest.raises(BudgetExceeded):
        asyncio.run(_executor(agent, audit).run(_plan([_step()]), parent))

    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert [event.status for event in steps] == ["ok"]
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "denied"
    assert runs[-1].error_code == "budget_exceeded"


def test_budget_blocks_next_step():
    audit = FakeAudit()
    agent = ScriptedAgent([(1.0, "first")])
    parent = _parent(budget_usd=1.0)
    plan = _plan(
        [
            _step("a"),
            _step("b", depends_on=["a"]),
        ],
        strategy="sequential",
    )

    with pytest.raises(BudgetExceeded):
        asyncio.run(_executor(agent, audit).run(plan, parent))

    assert len(agent.calls) == 1
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert [event.target for event in steps] == ["a"]


def test_step_budget_exceeded():
    audit = FakeAudit()
    agent = ScriptedAgent([(1.0, "over")])
    plan = _plan([_step(budget_usd=0.5)])

    with pytest.raises(BudgetExceeded):
        asyncio.run(_executor(agent, audit).run(plan, _parent()))

    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].status == "error"
    assert steps[-1].error_code == "budget_exceeded"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "denied"


def test_cancellation_before_run():
    audit = FakeAudit()
    agent = ScriptedAgent([(0.0, "ok")])

    async def scenario() -> None:
        token = CancellationToken()
        token.cancel()
        with pytest.raises(PlanCancelled):
            await _executor(agent, audit).run(_plan([_step()]), _parent(), cancel=token)

    asyncio.run(scenario())
    assert agent.calls == []
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "cancelled"


def test_cancellation_during_step():
    audit = FakeAudit()
    started = asyncio.Event()

    async def slow(invocation: Invocation) -> InvocationResult:
        started.set()
        await asyncio.sleep(10)
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text="late",
        )

    async def scenario() -> None:
        token = CancellationToken()
        executor = _executor(slow, audit)
        task = asyncio.create_task(
            executor.run(_plan([_step(timeout_seconds=30)]), _parent(), cancel=token)
        )
        await started.wait()
        token.cancel()
        with pytest.raises(PlanCancelled):
            await task

    asyncio.run(scenario())
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].error_code == "cancelled"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "cancelled"


def test_result_cost_is_summed():
    agent = ScriptedAgent([(0.2, "a"), (0.3, "b")])
    plan = _plan(
        [
            _step("a"),
            _step("b", depends_on=["a"]),
        ],
        strategy="sequential",
    )

    result = asyncio.run(_executor(agent).run(plan, _parent(budget_usd=1.0)))

    assert result.final_text == "b"
    assert result.cost_usd == pytest.approx(0.5)
