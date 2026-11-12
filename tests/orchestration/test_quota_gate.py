"""SLICE-028: plan runs respect per-tenant quotas."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adk_agent.core import (
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
    QuotaPolicy,
)
from adk_agent.orchestration import AgentGrantPolicyEngine, PlanExecutor
from adk_agent.runtime.quota import InMemoryQuotaManager, QuotaExceeded

_DIGEST = "d" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class Recorder:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, invocation: Invocation) -> InvocationResult:
        self.calls += 1
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{invocation.input}",
        )


def _plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="single",
        steps=[
            PlanStep(
                id="only",
                agent_ref=AgentRef(id="worker", version="1.0.0", digest=_DIGEST),
            )
        ],
    )


def _invocation() -> Invocation:
    return Invocation(
        run_id="run-1",
        trace_id="trace-1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="flow", version="1.0.0", digest=_DIGEST),
        input="hello",
    )


def test_plan_denied_over_quota():
    recorder = Recorder()
    auditor = FakeAudit()
    executor = PlanExecutor(
        {"worker": recorder.call},
        policy=AgentGrantPolicyEngine(["worker"]),
        audit=auditor,
    )
    quota = InMemoryQuotaManager()
    policy = QuotaPolicy(max_runs=1, window_seconds=60)

    asyncio.run(executor.run(_plan(), _invocation(), quota=quota, quota_policy=policy))
    with pytest.raises(QuotaExceeded):
        asyncio.run(executor.run(_plan(), _invocation(), quota=quota, quota_policy=policy))

    assert recorder.calls == 1
    last = auditor.events[-1]
    assert last.action == "orchestration.run"
    assert last.status == "denied"
    assert last.error_code == "quota_exceeded"


def test_plan_without_quota_is_unlimited():
    recorder = Recorder()
    executor = PlanExecutor(
        {"worker": recorder.call},
        policy=AgentGrantPolicyEngine(["worker"]),
    )

    for _ in range(2):
        asyncio.run(executor.run(_plan(), _invocation()))

    assert recorder.calls == 2
