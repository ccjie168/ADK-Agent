"""SLICE-118: approval history over the file inbox."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from adk_agent.approvals import FileApprovalInbox
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc
NOW = datetime(2026, 11, 16, 10, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _inbox(tmp_path, *, clock: Clock | None = None) -> FileApprovalInbox:
    return FileApprovalInbox(tmp_path / "inbox", clock=clock or Clock())


def _request(
    request_id: str,
    *,
    tenant: str = "acme",
    requested_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        input="deploy prod",
        reason="touches production",
        requested_at=requested_at,
        expires_at=expires_at,
    )


def test_decided_records_are_listed(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock=clock)
    inbox.submit(_request("approved-1", expires_at=NOW + timedelta(hours=1)))
    inbox.submit(_request("denied-1", expires_at=NOW + timedelta(hours=1)))
    clock.now = NOW + timedelta(minutes=1)
    inbox.decide("approved-1", approved=True, approver="alice", reason="ok")
    clock.now = NOW + timedelta(minutes=2)
    inbox.decide("denied-1", approved=False, approver="bob", reason="no")

    entries = inbox.history()

    assert [(entry.request.request_id, entry.status) for entry in entries] == [
        ("denied-1", "denied"),
        ("approved-1", "approved"),
    ]
    by_id = {entry.request.request_id: entry for entry in entries}
    assert by_id["approved-1"].decision is not None
    assert by_id["approved-1"].decision.approved is True
    assert by_id["approved-1"].terminal_at == NOW + timedelta(minutes=1)
    assert by_id["denied-1"].decision is not None
    assert by_id["denied-1"].decision.approver == "bob"
    assert by_id["denied-1"].archived is False


def test_expired_record_is_listed(tmp_path):
    inbox = _inbox(tmp_path)
    deadline = NOW - timedelta(minutes=5)
    inbox.submit(_request("expired-1", expires_at=deadline))

    [entry] = inbox.history()

    assert entry.request.request_id == "expired-1"
    assert entry.status == "expired"
    assert entry.decision is None
    assert entry.terminal_at == deadline


def test_pending_record_is_excluded(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request("pending-1", expires_at=NOW + timedelta(hours=1)))

    assert inbox.history() == []


def test_archived_records_are_included(tmp_path):
    clock = Clock(NOW - timedelta(hours=2))
    inbox = _inbox(tmp_path, clock=clock)
    inbox.submit(
        _request(
            "archived-1",
            requested_at=NOW - timedelta(hours=2),
            expires_at=NOW - timedelta(hours=1),
        )
    )
    inbox.decide("archived-1", approved=True, approver="alice")

    result = inbox.prune(60, now=NOW)

    assert result.archived == 1
    [entry] = inbox.history()
    assert entry.request.request_id == "archived-1"
    assert entry.status == "approved"
    assert entry.archived is True


def test_tenant_and_status_filters(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock=clock)
    future = NOW + timedelta(hours=1)
    inbox.submit(_request("acme-approved", tenant="acme", expires_at=future))
    inbox.submit(_request("acme-denied", tenant="acme", expires_at=future))
    inbox.submit(_request("other-approved", tenant="other", expires_at=future))
    inbox.submit(_request("acme-expired", tenant="acme", expires_at=NOW - timedelta(minutes=1)))
    inbox.decide("acme-approved", approved=True, approver="alice")
    inbox.decide("acme-denied", approved=False, approver="alice")
    inbox.decide("other-approved", approved=True, approver="carol")

    acme = {entry.request.request_id for entry in inbox.history(tenant="acme")}
    approved = {entry.request.request_id for entry in inbox.history(status="approved")}
    denied = [entry.request.request_id for entry in inbox.history(tenant="acme", status="denied")]

    assert acme == {"acme-approved", "acme-denied", "acme-expired"}
    assert approved == {"acme-approved", "other-approved"}
    assert denied == ["acme-denied"]
    with pytest.raises(ValueError):
        inbox.history(status="pending")


def test_order_and_limit(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock=clock)
    future = NOW + timedelta(hours=1)
    for request_id in ("r0", "r1", "r2"):
        inbox.submit(_request(request_id, expires_at=future))
    for request_id, minute in (("r0", 1), ("r1", 3), ("r2", 2)):
        clock.now = NOW + timedelta(minutes=minute)
        inbox.decide(request_id, approved=True, approver="alice")

    ordered = [entry.request.request_id for entry in inbox.history()]

    assert ordered == ["r1", "r2", "r0"]
    assert [entry.request.request_id for entry in inbox.history(limit=2)] == ["r1", "r2"]
    assert [entry.request.request_id for entry in inbox.history(limit=1)] == ["r1"]
    assert [entry.request.request_id for entry in inbox.history(limit=0)] == ["r1"]
    assert len(inbox.history(limit=1000)) == 3
