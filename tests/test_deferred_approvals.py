"""SLICE-0049-1: deferred approvals return a pending result and resume later."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from adk_agent.approvals import FileApprovalInbox
from adk_agent.audit import ListAuditSink
from adk_agent.core import (
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanPending,
    PlanResult,
    PlanStep,
    Principal,
)
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    ApprovalDenied,
    InMemoryCheckpointStore,
    PlanExecutor,
)

_DIGEST = "d" * 64


def _ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="deferred-flow",
        version="1.0.0",
        strategy="sequential",
        steps=[
            PlanStep(id="answer", agent_ref=_ref("support")),
            PlanStep(
                id="ticket",
                agent_ref=_ref("ticket_writer"),
                input="建单",
                risk_level="L3",
                approval_reason="写操作",
            ),
        ],
    )


def _invocation() -> Invocation:
    return Invocation(
        run_id="run-1",
        trace_id="trace-1",
        principal=Principal(tenant="local", subject="tester", kind="human"),
        agent_ref=_ref("flow"),
        input="客户无法登录",
    )


def _executor(calls: list[str], *, defer: bool = True, audit=None, notifier=None) -> PlanExecutor:
    async def support(invocation: Invocation) -> InvocationResult:
        calls.append("support")
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text="先重置密码",
        )

    async def ticket_writer(invocation: Invocation) -> InvocationResult:
        calls.append("ticket_writer")
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text="已创建工单 t-9",
        )

    return PlanExecutor(
        {"support": support, "ticket_writer": ticket_writer},
        policy=AgentGrantPolicyEngine(["support", "ticket_writer"]),
        audit=audit,
        checkpoints=InMemoryCheckpointStore(),
        defer_approvals=defer,
        notifier=notifier,
    )


def test_defer_rejects_other_strategies():
    from adk_agent.core import RouteWhen

    calls: list[str] = []
    executor = _executor(calls)
    plan = OrchestrationPlan(
        plan_id="routing-flow",
        version="1.0.0",
        strategy="routing",
        steps=[
            PlanStep(id="answer", agent_ref=_ref("support"), route_when=RouteWhen(contains="登录")),
            PlanStep(id="ticket", agent_ref=_ref("ticket_writer"), risk_level="L3"),
        ],
    )

    with pytest.raises(ValueError, match="single and sequential"):
        asyncio.run(executor.run(plan, _invocation()))
    assert calls == []


def test_deferred_run_returns_pending_and_creates_request(tmp_path):
    calls: list[str] = []
    audit = ListAuditSink()
    inbox = FileApprovalInbox(tmp_path / "approvals", poll_seconds=0.05)
    executor = _executor(calls, audit=audit)

    result = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))

    assert isinstance(result, PlanPending)
    assert result.step_id == "ticket"
    assert (
        result.request_id == uuid.uuid5(uuid.NAMESPACE_URL, "adk-approval:local:run-1:ticket").hex
    )
    assert result.expires_at is not None
    assert result.expires_at.tzinfo is not None
    [pending] = inbox.pending()
    assert pending.request_id == result.request_id
    assert calls == ["support"]
    assert any(event.action == "orchestration.deferral" for event in audit.recent(50))


def test_approved_resume_runs_the_remaining_step(tmp_path):
    calls: list[str] = []
    inbox = FileApprovalInbox(tmp_path / "approvals", poll_seconds=0.05)
    executor = _executor(calls)

    pending = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))
    assert isinstance(pending, PlanPending)
    inbox.decide(pending.request_id, approved=True, approver="tester")

    result = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))

    assert isinstance(result, PlanResult)
    assert "t-9" in result.final_text
    assert calls == ["support", "ticket_writer"]


def test_denied_resume_raises_and_skips_the_step(tmp_path):
    calls: list[str] = []
    inbox = FileApprovalInbox(tmp_path / "approvals", poll_seconds=0.05)
    executor = _executor(calls)

    pending = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))
    inbox.decide(pending.request_id, approved=False, approver="tester")

    with pytest.raises(ApprovalDenied):
        asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))
    assert calls == ["support"]


def test_pending_reentry_is_stable(tmp_path):
    calls: list[str] = []
    inbox = FileApprovalInbox(tmp_path / "approvals", poll_seconds=0.05)
    executor = _executor(calls)

    first = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))
    second = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))

    assert isinstance(second, PlanPending)
    assert second.request_id == first.request_id
    assert calls == ["support"]


def test_sync_mode_still_waits(monkeypatch):
    calls: list[str] = []
    executor = _executor(calls, defer=False)
    assert executor.defer_approvals is False

    class DenyGate:
        async def request(self, request):
            from adk_agent.core import ApprovalDecision

            return ApprovalDecision(
                request_id=request.request_id,
                approved=False,
                approver="tester",
                decided_at=datetime.now(timezone.utc),
            )

    with pytest.raises(ApprovalDenied):
        asyncio.run(executor.run(_plan(), _invocation(), approvals=DenyGate()))
    assert calls == ["support"]


def test_defer_requires_a_submit_capable_gate():
    from adk_agent.orchestration import ApprovalProtocolError

    calls: list[str] = []
    executor = _executor(calls)

    class RequestOnlyGate:
        async def request(self, request):
            raise AssertionError("deferred mode must not block")

    with pytest.raises(ApprovalProtocolError):
        asyncio.run(executor.run(_plan(), _invocation(), approvals=RequestOnlyGate()))


def test_pending_expires_from_the_defer_ttl(tmp_path):
    calls: list[str] = []
    inbox = FileApprovalInbox(tmp_path / "approvals", poll_seconds=0.05)
    executor = _executor(calls)

    result = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))

    assert isinstance(result, PlanPending)
    assert result.expires_at is not None
    assert (result.expires_at - datetime.now(timezone.utc)).total_seconds() <= 3600


class FakeNotifier:
    def __init__(self) -> None:
        self.notices = []

    async def notify(self, notice):
        self.notices.append(notice)


def test_executor_notifies_on_defer_and_decision(tmp_path):
    calls: list[str] = []
    inbox = FileApprovalInbox(tmp_path / "approvals", poll_seconds=0.05)
    notifier = FakeNotifier()
    executor = _executor(calls, notifier=notifier)

    pending = asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))
    [submitted] = notifier.notices
    assert submitted.kind == "submitted"
    assert submitted.request_id == pending.request_id
    assert submitted.run_id == "run-1"

    inbox.decide(pending.request_id, approved=True, approver="tester")
    asyncio.run(executor.run(_plan(), _invocation(), approvals=inbox))

    assert [notice.kind for notice in notifier.notices] == ["submitted", "decided"]
    assert notifier.notices[-1].approved is True
    assert notifier.notices[-1].approver == "tester"
