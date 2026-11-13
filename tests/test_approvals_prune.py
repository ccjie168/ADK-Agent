"""SLICE-051: archive or delete terminal approval records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adk_agent.approvals import FileApprovalInbox
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = _AT) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _request(request_id: str = "req-1", *, expires_at: datetime | None = None) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        input="deploy prod",
        reason="touches production",
        requested_at=_AT,
        expires_at=expires_at,
    )


def _inbox(tmp_path, clock: Clock) -> FileApprovalInbox:
    return FileApprovalInbox(tmp_path, poll_seconds=0.01, clock=clock)


def _decided(tmp_path, clock: Clock, request_id: str = "req-1") -> FileApprovalInbox:
    inbox = _inbox(tmp_path, clock)
    inbox.submit(_request(request_id))
    inbox.decide(request_id, approved=True, approver="bob")
    return inbox


def test_archive_moves_terminal(tmp_path):
    clock = Clock()
    inbox = _decided(tmp_path, clock)
    clock.now = _AT + timedelta(days=10)

    result = inbox.prune(60)

    assert result.archived == 1
    assert result.deleted == 0
    assert not (tmp_path / "req-1.request.json").exists()
    assert not (tmp_path / "req-1.decision.json").exists()
    assert (tmp_path / "archive" / "req-1.request.json").exists()
    assert (tmp_path / "archive" / "req-1.decision.json").exists()
    assert inbox.get("req-1") is None
    assert inbox.pending() == []


def test_delete_removes_terminal(tmp_path):
    clock = Clock()
    inbox = _decided(tmp_path, clock)
    clock.now = _AT + timedelta(days=10)

    result = inbox.prune(60, archive=False)

    assert result.deleted == 1
    assert not (tmp_path / "req-1.request.json").exists()
    assert not (tmp_path / "req-1.decision.json").exists()
    assert not (tmp_path / "archive").exists()


def test_recent_terminal_kept(tmp_path):
    clock = Clock()
    inbox = _decided(tmp_path, clock)
    clock.now = _AT + timedelta(seconds=30)

    result = inbox.prune(60)

    assert result.kept == 1
    assert (tmp_path / "req-1.request.json").exists()


def test_pending_kept(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock)
    inbox.submit(_request(expires_at=_AT + timedelta(days=1)))
    clock.now = _AT + timedelta(hours=2)

    result = inbox.prune(60)

    assert result.kept == 1
    assert len(inbox.pending()) == 1


def test_expired_without_decision_archived(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock)
    inbox.submit(_request(expires_at=_AT))
    clock.now = _AT + timedelta(days=1)

    result = inbox.prune(60)

    assert result.archived == 1
    assert (tmp_path / "archive" / "req-1.request.json").exists()
    assert not (tmp_path / "req-1.decision.json").exists()


def test_no_deadline_pending_kept(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock)
    inbox.submit(_request())
    clock.now = _AT + timedelta(days=365)

    result = inbox.prune(60)

    assert result.kept == 1
    assert (tmp_path / "req-1.request.json").exists()


def test_result_counts(tmp_path):
    clock = Clock()
    inbox = _decided(tmp_path, clock, "decided")
    inbox.submit(_request("expired", expires_at=_AT))
    inbox.submit(_request("pending", expires_at=_AT + timedelta(days=30)))
    clock.now = _AT + timedelta(days=1)

    result = inbox.prune(60)

    assert (result.archived, result.deleted, result.kept) == (2, 0, 1)
    assert inbox.pending()[0].request_id == "pending"


def test_archived_request_is_gone(tmp_path):
    clock = Clock()
    inbox = _decided(tmp_path, clock)
    clock.now = _AT + timedelta(days=10)

    inbox.prune(60)

    assert inbox.get("req-1") is None
    assert inbox.pending() == []
    assert (tmp_path / "archive").is_dir()


def test_archive_target_exists_is_kept(tmp_path):
    clock = Clock()
    inbox = _decided(tmp_path, clock)
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "req-1.request.json").write_text("{}", encoding="utf-8")
    clock.now = _AT + timedelta(days=10)

    result = inbox.prune(60)

    assert result.kept == 1
    assert (tmp_path / "req-1.request.json").exists()
