"""SLICE-045: the file-backed approval inbox."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from adk_agent.approvals import (
    ApprovalConflict,
    ApprovalNotFound,
    FileApprovalInbox,
    InvalidApprovalRequest,
)
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


def _request(request_id: str = "req-1", *, tenant: str = "acme", input_text: str = "deploy prod"):
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        input=input_text,
        reason="touches production",
        requested_at=_AT,
    )


def _inbox(root) -> FileApprovalInbox:
    return FileApprovalInbox(root, poll_seconds=0.01)


async def _until_pending(inbox: FileApprovalInbox) -> None:
    for _ in range(200):
        if inbox.pending():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("request never became pending")


def test_submit_then_pending(tmp_path):
    inbox = _inbox(tmp_path / "inbox")
    request = _request()

    inbox.submit(request)

    assert inbox.pending() == [request]


def test_decide_removes_from_pending(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())

    decision = inbox.decide("req-1", approved=True, approver="bob", reason="looks fine")

    assert decision.approved is True
    assert decision.approver == "bob"
    assert decision.request_id == "req-1"
    assert inbox.pending() == []
    record = inbox.get("req-1")
    assert record is not None
    assert record.decision == decision


def test_second_decision_conflicts(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())
    first = inbox.decide("req-1", approved=True, approver="bob")

    with pytest.raises(ApprovalConflict):
        inbox.decide("req-1", approved=False, approver="mallory")

    record = inbox.get("req-1")
    assert record is not None
    assert record.decision == first


def test_unknown_request_not_found(tmp_path):
    inbox = _inbox(tmp_path)

    assert inbox.get("missing") is None
    with pytest.raises(ApprovalNotFound):
        inbox.decide("missing", approved=True, approver="bob")


def test_unsafe_request_id_rejected(tmp_path):
    root = tmp_path / "inbox"
    inbox = _inbox(root)

    with pytest.raises(InvalidApprovalRequest):
        inbox.submit(_request("../evil"))
    with pytest.raises(InvalidApprovalRequest):
        inbox.decide("../evil", approved=True, approver="bob")

    assert not (tmp_path / "evil.request.json").exists()
    assert not (tmp_path / "evil.decision.json").exists()


def test_same_request_is_idempotent(tmp_path):
    inbox = _inbox(tmp_path)
    request = _request()

    inbox.submit(request)
    inbox.submit(request)

    assert inbox.pending() == [request]


def test_conflicting_resubmit_rejected(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())

    with pytest.raises(ApprovalConflict):
        inbox.submit(_request(input_text="delete prod"))


def test_gate_waits_for_decision(tmp_path):
    executor_side = _inbox(tmp_path)
    console_side = _inbox(tmp_path)

    async def scenario():
        task = asyncio.create_task(executor_side.request(_request()))
        await _until_pending(console_side)
        console_side.decide("req-1", approved=True, approver="bob")
        return await asyncio.wait_for(task, timeout=2)

    decision = asyncio.run(scenario())
    assert decision.approved is True
    assert decision.approver == "bob"


def test_gate_cancellation_leaves_pending(tmp_path):
    inbox = _inbox(tmp_path)

    async def scenario():
        task = asyncio.create_task(inbox.request(_request()))
        await _until_pending(inbox)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(inbox.pending()) == 1


def test_two_inboxes_share_decisions(tmp_path):
    writer = _inbox(tmp_path)
    reader = _inbox(tmp_path)
    writer.submit(_request(tenant="other"))

    [seen] = reader.pending()
    assert seen.request_id == "req-1"
    reader.decide("req-1", approved=False, approver="carol")

    record = writer.get("req-1")
    assert record is not None
    assert record.decision is not None
    assert record.decision.approved is False
    assert record.decision.approver == "carol"
