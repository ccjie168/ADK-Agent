"""SLICE-049: approval requests expire and notify on submit."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest

from adk_agent.approvals import ApprovalConflict, ApprovalExpired, FileApprovalInbox
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = _AT) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _request(
    request_id: str = "req-1",
    *,
    requested_at: datetime = _AT,
    expires_at: datetime | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        input="deploy prod",
        reason="touches production",
        requested_at=requested_at,
        expires_at=expires_at,
    )


def _inbox(tmp_path, **kwargs) -> FileApprovalInbox:
    kwargs.setdefault("poll_seconds", 0.01)
    return FileApprovalInbox(tmp_path, **kwargs)


async def _until_pending(inbox: FileApprovalInbox) -> None:
    for _ in range(200):
        if inbox.pending():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("request never became pending")


def test_pending_excludes_expired(tmp_path):
    clock = Clock(_AT + timedelta(hours=2))
    inbox = _inbox(tmp_path, clock=clock)
    inbox.submit(_request(expires_at=_AT + timedelta(hours=1)))

    assert inbox.pending() == []


def test_decide_expired_raises(tmp_path):
    clock = Clock(_AT + timedelta(hours=2))
    inbox = _inbox(tmp_path, clock=clock)
    inbox.submit(_request(expires_at=_AT + timedelta(hours=1)))

    with pytest.raises(ApprovalExpired):
        inbox.decide("req-1", approved=True, approver="bob")

    record = inbox.get("req-1")
    assert record is not None
    assert record.decision is None


def test_decided_request_is_not_expired(tmp_path):
    clock = Clock(_AT)
    inbox = _inbox(tmp_path, clock=clock)
    inbox.submit(_request(expires_at=_AT + timedelta(hours=1)))
    first = inbox.decide("req-1", approved=True, approver="bob")

    clock.now = _AT + timedelta(hours=2)

    with pytest.raises(ApprovalConflict):
        inbox.decide("req-1", approved=False, approver="mallory")
    record = inbox.get("req-1")
    assert record is not None
    assert record.decision == first


def test_gate_raises_when_expired(tmp_path):
    clock = Clock(_AT + timedelta(hours=2))
    inbox = _inbox(tmp_path, clock=clock)

    with pytest.raises(ApprovalExpired):
        asyncio.run(inbox.request(_request(expires_at=_AT + timedelta(hours=1))))


def test_request_expiry_wins_over_ttl(tmp_path):
    clock = Clock(_AT + timedelta(hours=2))
    inbox = _inbox(tmp_path, clock=clock, ttl_seconds=1)
    request = _request(expires_at=_AT + timedelta(hours=10))

    inbox.submit(request)

    assert inbox.pending() == [request]


def test_ttl_fallback(tmp_path):
    clock = Clock(_AT + timedelta(seconds=61))
    inbox = _inbox(tmp_path, clock=clock, ttl_seconds=60)
    inbox.submit(_request())

    assert inbox.pending() == []
    with pytest.raises(ApprovalExpired):
        inbox.decide("req-1", approved=True, approver="bob")


def test_no_deadline_never_expires(tmp_path):
    clock = Clock(_AT + timedelta(days=365))
    inbox = _inbox(tmp_path, clock=clock)
    request = _request()
    inbox.submit(request)

    assert inbox.pending() == [request]


def test_on_submit_called(tmp_path):
    seen: list[ApprovalRequest] = []

    async def notify(request: ApprovalRequest) -> None:
        seen.append(request)

    clock = Clock(_AT)
    inbox = _inbox(tmp_path, clock=clock, on_submit=notify)

    async def scenario() -> None:
        task = asyncio.create_task(inbox.request(_request(expires_at=_AT + timedelta(hours=1))))
        await _until_pending(inbox)
        inbox.decide("req-1", approved=True, approver="bob")
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())

    assert [request.request_id for request in seen] == ["req-1"]


def test_on_submit_failure_is_logged(tmp_path, caplog):
    async def notify(request: ApprovalRequest) -> None:
        raise RuntimeError("notifier down")

    clock = Clock(_AT)
    inbox = _inbox(tmp_path, clock=clock, on_submit=notify)

    async def scenario() -> None:
        task = asyncio.create_task(inbox.request(_request(expires_at=_AT + timedelta(hours=1))))
        await _until_pending(inbox)
        inbox.decide("req-1", approved=True, approver="bob")
        decision = await asyncio.wait_for(task, timeout=2)
        assert decision.approved is True

    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())

    assert any("notification" in record.message for record in caplog.records)
