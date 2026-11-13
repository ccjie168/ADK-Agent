"""SLICE-049: plan approvals carry a deadline."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from adk_agent.core import (
    AgentRef,
    ApprovalDecision,
    ApprovalRequest,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
)
from adk_agent.orchestration import AgentGrantPolicyEngine, CallbackApprovalGate, PlanExecutor

_DIGEST = "d" * 64
UTC = timezone.utc


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class Recorder:
    async def __call__(self, invocation: Invocation) -> InvocationResult:
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text="done",
        )


def _ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent(*, deadline: datetime | None) -> Invocation:
    return Invocation(
        run_id="parent-run",
        trace_id="trace-1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=_ref("flow"),
        input="do the thing",
        deadline=deadline,
    )


def _plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="single",
        steps=[
            PlanStep(
                id="a",
                agent_ref=_ref("worker"),
                requires_approval=True,
                approval_reason="touches production",
            )
        ],
    )


def test_deadline_sets_expiry():
    requests: list[ApprovalRequest] = []

    async def approve(request: ApprovalRequest) -> ApprovalDecision:
        requests.append(request)
        return ApprovalDecision(
            request_id=request.request_id,
            approved=True,
            approver="alice",
            decided_at=datetime.now(UTC),
        )

    deadline = datetime.now(UTC) + timedelta(seconds=10)
    executor = PlanExecutor(
        {"worker": Recorder()},
        policy=AgentGrantPolicyEngine(["worker"]),
        audit=FakeAudit(),
    )

    asyncio.run(
        executor.run(_plan(), _parent(deadline=deadline), approvals=CallbackApprovalGate(approve))
    )

    [request] = requests
    assert request.expires_at is not None
    remaining = (request.expires_at - request.requested_at).total_seconds()
    assert 0 < remaining <= 10
