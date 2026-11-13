"""SLICE-051: the approvals prune subcommand."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adk_agent import cli
from adk_agent.approvals import FileApprovalInbox
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


class Clock:
    def __call__(self) -> datetime:
        return _AT


def _seed(root, request_id: str = "req-1") -> None:
    inbox = FileApprovalInbox(root, clock=Clock())
    inbox.submit(
        ApprovalRequest(
            request_id=request_id,
            run_id="run-1",
            trace_id="trace-1",
            step_id="step-a",
            agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
            principal=Principal(tenant="acme", subject="alice", kind="human"),
            input="deploy prod",
            requested_at=_AT,
        )
    )
    inbox.decide(request_id, approved=True, approver="bob")


def test_cli_archives(tmp_path, capsys):
    root = tmp_path / "inbox"
    _seed(root)

    cli.main(["approvals", "prune", "--dir", str(root), "--older-than", "60"])

    assert "archived 1 requests" in capsys.readouterr().out
    assert (root / "archive" / "req-1.request.json").exists()
    assert not (root / "req-1.request.json").exists()


def test_cli_deletes(tmp_path, capsys):
    root = tmp_path / "inbox"
    _seed(root)

    cli.main(["approvals", "prune", "--dir", str(root), "--older-than", "60", "--delete"])

    assert "deleted 1 requests" in capsys.readouterr().out
    assert not (root / "req-1.request.json").exists()


def test_cli_requires_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADK_APPROVAL_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(["approvals", "prune", "--older-than", "60"])

    assert exc.value.code == 1
    assert "approval dir" in capsys.readouterr().err


def test_cli_rejects_nonpositive(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["approvals", "prune", "--dir", str(tmp_path), "--older-than", "0"])

    assert exc.value.code == 1
    assert "older-than" in capsys.readouterr().err
