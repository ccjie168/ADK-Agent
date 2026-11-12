"""SLICE-027: plan steps can require human approval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

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
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    ApprovalDenied,
    ApprovalProtocolError,
    ApprovalRequired,
    ApprovalTimeout,
    CallbackApprovalGate,
    PlanExecutor,
)

_DIGEST = "d" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[Invocation] = []

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{invocation.input}",
        )


def _ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent(**overrides) -> Invocation:
    data = {
        "run_id": "parent-run",
        "trace_id": "trace-1",
        "principal": Principal(tenant="t1", subject="alice", kind="human"),
        "agent_ref": _ref("flow"),
        "input": "do the thing",
    }
    data.update(overrides)
    return Invocation(**data)


def _step(**overrides) -> PlanStep:
    data = {
        "id": "a",
        "agent_ref": _ref("worker"),
        "requires_approval": True,
        "approval_reason": "touches production",
    }
    data.update(overrides)
    return PlanStep(**data)


def _plan(step: PlanStep | None = None) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="single",
        steps=[step or _step()],
    )


def _executor(recorder: Recorder, audit: FakeAudit) -> PlanExecutor:
    return PlanExecutor(
        {"worker": recorder},
        policy=AgentGrantPolicyEngine(["worker"]),
        audit=audit,
    )


def _decision(request: ApprovalRequest, approved: bool, approver: str = "alice"):
    return ApprovalDecision(
        request_id=request.request_id,
        approved=approved,
        approver=approver,
        reason="ok",
        decided_at=datetime.now(timezone.utc),
    )


def test_approved_step_runs():
    audit = FakeAudit()
    recorder = Recorder()
    requests: list[ApprovalRequest] = []

    async def approve(request: ApprovalRequest) -> ApprovalDecision:
        requests.append(request)
        return _decision(request, True)

    result = asyncio.run(
        _executor(recorder, audit).run(_plan(), _parent(), approvals=CallbackApprovalGate(approve))
    )

    assert result.final_text == "out:do the thing"
    assert len(recorder.calls) == 1
    [request] = requests
    assert request.step_id == "a"
    assert request.trace_id == "trace-1"
    assert request.agent_ref.id == "worker"
    assert request.principal.subject == "alice"
    assert request.input == "do the thing"
    assert request.reason == "touches production"

    approvals = [event for event in audit.events if event.action == "orchestration.approval"]
    assert len(approvals) == 1
    assert approvals[0].status == "ok"
    assert approvals[0].approver == "alice"
    assert approvals[0].policy_decision_id == request.request_id
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].status == "ok"


def test_denied_step_does_not_run():
    audit = FakeAudit()
    recorder = Recorder()

    def deny(request: ApprovalRequest) -> ApprovalDecision:
        return _decision(request, False, approver="bob")

    with pytest.raises(ApprovalDenied):
        asyncio.run(
            _executor(recorder, audit).run(_plan(), _parent(), approvals=CallbackApprovalGate(deny))
        )

    assert recorder.calls == []
    approvals = [event for event in audit.events if event.action == "orchestration.approval"]
    assert approvals[-1].status == "denied"
    assert approvals[-1].approver == "bob"
    assert approvals[-1].error_code == "approval_denied"
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].status == "denied"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].status == "denied"
    assert runs[-1].error_code == "approval_denied"


def test_missing_gate_fails_closed():
    audit = FakeAudit()
    recorder = Recorder()

    with pytest.raises(ApprovalRequired):
        asyncio.run(_executor(recorder, audit).run(_plan(), _parent()))

    assert recorder.calls == []
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].status == "denied"
    assert steps[-1].error_code == "approval_required"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "approval_required"


def test_approval_protocol_mismatch():
    audit = FakeAudit()
    recorder = Recorder()

    def wrong(request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            request_id="other",
            approved=True,
            approver="alice",
            decided_at=datetime.now(timezone.utc),
        )

    with pytest.raises(ApprovalProtocolError):
        asyncio.run(
            _executor(recorder, audit).run(
                _plan(), _parent(), approvals=CallbackApprovalGate(wrong)
            )
        )

    assert recorder.calls == []
    approvals = [event for event in audit.events if event.action == "orchestration.approval"]
    assert approvals[-1].error_code == "approval_protocol"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "approval_protocol"


def test_approval_timeout():
    audit = FakeAudit()
    recorder = Recorder()

    async def slow(request: ApprovalRequest) -> ApprovalDecision:
        await asyncio.sleep(2)
        return _decision(request, True)

    parent = _parent(deadline=datetime.now(timezone.utc) + timedelta(seconds=0.2))

    with pytest.raises(ApprovalTimeout):
        asyncio.run(
            _executor(recorder, audit).run(_plan(), parent, approvals=CallbackApprovalGate(slow))
        )

    assert recorder.calls == []
    steps = [event for event in audit.events if event.action == "orchestration.step"]
    assert steps[-1].error_code == "approval_timeout"
    runs = [event for event in audit.events if event.action == "orchestration.run"]
    assert runs[-1].error_code == "approval_timeout"
