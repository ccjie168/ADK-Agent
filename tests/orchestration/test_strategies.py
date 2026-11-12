"""SLICE-025: routing and fan-out/fan-in plans."""

from __future__ import annotations

import asyncio
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
    RouteWhen,
)
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    BudgetExceeded,
    NoRoute,
    PlanExecutor,
)

_DIGEST = "d" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class Recorder:
    def __init__(self, costs: dict[str, float] | None = None) -> None:
        self.calls: list[Invocation] = []
        self.costs = costs or {}

    async def call(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        name = invocation.agent_ref.id
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{name}:{invocation.input}",
            cost_usd=self.costs.get(name, 0.0),
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


def _plan(steps: list[PlanStep], strategy: str, max_parallel: int = 1) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy=strategy,
        max_parallel=max_parallel,
        steps=steps,
    )


def _executor(agents: dict[str, Any], audit: FakeAudit | None = None) -> PlanExecutor:
    return PlanExecutor(
        agents,
        policy=AgentGrantPolicyEngine(list(agents)),
        audit=audit,
    )


def test_routing_selects_matching_step():
    audit = FakeAudit()
    recorder = Recorder()
    plan = _plan(
        [
            _step("billing", route_when={"contains": "bill"}),
            _step("fallback"),
        ],
        "routing",
    )

    result = asyncio.run(
        _executor({"billing": recorder.call, "fallback": recorder.call}, audit).run(
            plan, _parent("please bill me")
        )
    )

    assert result.final_text == "out:billing:please bill me"
    assert set(result.outputs) == {"billing"}
    assert [call.agent_ref.id for call in recorder.calls] == ["billing"]
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert [event.target for event in steps] == ["billing"]


def test_routing_uses_default():
    recorder = Recorder()
    plan = _plan(
        [
            _step("billing", route_when={"contains": "bill"}),
            _step("fallback"),
        ],
        "routing",
    )

    result = asyncio.run(
        _executor({"billing": recorder.call, "fallback": recorder.call}).run(plan, _parent("hello"))
    )

    assert result.final_text == "out:fallback:hello"
    assert [call.agent_ref.id for call in recorder.calls] == ["fallback"]


def test_routing_no_match_fails():
    audit = FakeAudit()
    recorder = Recorder()
    plan = _plan([_step("billing", route_when={"contains": "bill"})], "routing")

    with pytest.raises(NoRoute):
        asyncio.run(_executor({"billing": recorder.call}, audit).run(plan, _parent("hello")))

    assert recorder.calls == []
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "no_route"


def test_routing_validation():
    with pytest.raises(ValidationError):
        _plan([_step("a", route_when={"equals": "x"})], "sequential")
    with pytest.raises(ValidationError):
        _plan([_step("a"), _step("b")], "routing")
    with pytest.raises(ValidationError):
        _plan(
            [
                _step("fallback"),
                _step("a", route_when={"equals": "x"}),
            ],
            "routing",
        )
    with pytest.raises(ValidationError):
        _plan(
            [
                _step("a", route_when={"equals": "x"}, depends_on=["b"]),
                _step("b"),
            ],
            "routing",
        )
    with pytest.raises(ValidationError):
        RouteWhen(equals="x", contains="y")


def test_route_when_operators():
    assert RouteWhen(equals="x").matches("x")
    assert not RouteWhen(equals="x").matches("xy")
    assert RouteWhen(contains="x").matches("axb")
    assert RouteWhen(prefix="ab").matches("abc")
    assert not RouteWhen(prefix="ab").matches("zab")


def test_fan_out_runs_branches_concurrently():
    recorder = Recorder()
    a_started = asyncio.Event()
    b_started = asyncio.Event()

    async def branch_a(invocation: Invocation) -> InvocationResult:
        a_started.set()
        await b_started.wait()
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text="out:a",
        )

    async def branch_b(invocation: Invocation) -> InvocationResult:
        b_started.set()
        await a_started.wait()
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text="out:b",
        )

    plan = _plan(
        [
            _step("a", timeout_seconds=1),
            _step("b", timeout_seconds=1),
            _step(
                "join",
                depends_on=["a", "b"],
                inputs_from=["a", "b"],
                input="join",
                timeout_seconds=1,
            ),
        ],
        "fan_out",
        max_parallel=2,
    )

    result = asyncio.run(
        _executor({"a": branch_a, "b": branch_b, "join": recorder.call}).run(plan, _parent())
    )

    assert result.final_text == "out:join:join\n\nout:a\n\nout:b"
    assert set(result.outputs) == {"a", "b", "join"}
    [join_call] = recorder.calls
    assert join_call.agent_ref.id == "join"


def test_fan_out_requires_one_sink():
    with pytest.raises(ValidationError):
        _plan([_step("a"), _step("b")], "fan_out")


def test_fan_out_budget_post_check():
    audit = FakeAudit()
    recorder = Recorder({"a": 0.6, "b": 0.6, "join": 0.0})
    plan = _plan(
        [
            _step("a"),
            _step("b"),
            _step("join", depends_on=["a", "b"], inputs_from=["a", "b"]),
        ],
        "fan_out",
        max_parallel=2,
    )

    with pytest.raises(BudgetExceeded):
        asyncio.run(
            _executor(
                {"a": recorder.call, "b": recorder.call, "join": recorder.call},
                audit,
            ).run(plan, _parent(budget_usd=1.0))
        )

    assert {call.agent_ref.id for call in recorder.calls} == {"a", "b"}
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "denied"
    assert runs[-1].error_code == "budget_exceeded"
