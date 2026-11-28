"""SLICE-311: approval notices, the webhook notifier and the resumer."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from adk_agent.approval_resumer import ApprovalResumer
from adk_agent.approvals import ApprovalDecision, ApprovalHistoryEntry, ApprovalRequest
from adk_agent.core import AgentRef, ApprovalNotice, Principal
from adk_agent.notify import NotifierError, WebhookNotifier

_NOW = datetime(2026, 11, 28, tzinfo=timezone.utc)


def _notice(**overrides) -> ApprovalNotice:
    data = {
        "kind": "submitted",
        "request_id": "req-1",
        "tenant": "local",
        "run_id": "run-1",
        "step_id": "ticket",
    }
    data.update(overrides)
    return ApprovalNotice(**data)


def _entry(request_id: str, status: str = "approved", minutes: int = 0) -> ApprovalHistoryEntry:
    when = _NOW + timedelta(minutes=minutes)
    request = ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="ticket",
        agent_ref=AgentRef(id="ticket_writer", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant="local", subject="tester", kind="human"),
        input="x",
        requested_at=when,
    )
    decision = ApprovalDecision(
        request_id=request_id,
        approved=status == "approved",
        approver="tester",
        decided_at=when,
    )
    return ApprovalHistoryEntry(
        request=request, decision=decision, status=status, archived=False, terminal_at=when
    )


def test_notice_roundtrip():
    notice = _notice(kind="decided", approved=True, approver="tester")

    assert ApprovalNotice.model_validate_json(notice.model_dump_json()) == notice
    with pytest.raises(ValueError):
        _notice(expires_at=datetime(2026, 11, 28))  # naive timestamps are refused


def test_webhook_notifier_signs_and_retries():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500 if len(seen) == 1 else 200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = WebhookNotifier(
        "https://hook.example.test/approvals",
        secret="s3cret",  # pragma: allowlist secret
        client=client,
        retries=1,
        backoff_seconds=0,
    )
    notice = _notice()
    asyncio.run(notifier.notify(notice))
    asyncio.run(client.aclose())

    assert len(seen) == 2
    body = seen[0].content
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert seen[0].headers["x-adk-signature"] == expected
    assert json.loads(body)["request_id"] == notice.request_id


def test_webhook_notifier_gives_up():
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = WebhookNotifier(
        "https://hook.example.test/approvals",
        secret="s3cret",  # pragma: allowlist secret
        client=client,
        retries=1,
        backoff_seconds=0,
    )
    with pytest.raises(NotifierError):
        asyncio.run(notifier.notify(_notice()))
    asyncio.run(client.aclose())
    assert len(attempts) == 2


class FakeInbox:
    def __init__(self, entries):
        self.entries = entries
        self.polls = 0

    def history(self, *, limit=50, oldest_first=False, since=None):
        self.polls += 1
        rows = self.entries
        if since is not None:
            rows = [entry for entry in rows if entry.terminal_at > since]
        rows = sorted(rows, key=lambda entry: entry.terminal_at, reverse=not oldest_first)
        return rows[:limit]


def test_resumer_handles_each_decision_once():
    inbox = FakeInbox([_entry("req-1"), _entry("req-2", status="denied")])
    handled: list[str] = []

    async def handler(entry):
        handled.append(entry.request.request_id)

    resumer = ApprovalResumer(inbox, handler)
    assert asyncio.run(resumer.run_once()) == 2
    assert asyncio.run(resumer.run_once()) == 0
    assert handled == ["req-1", "req-2"]
    assert resumer.handled == 2


def test_resumer_survives_handler_errors():
    inbox = FakeInbox([_entry("bad"), _entry("good")])
    handled: list[str] = []

    async def handler(entry):
        if entry.request.request_id == "bad":
            raise RuntimeError("boom")
        handled.append(entry.request.request_id)

    resumer = ApprovalResumer(inbox, handler)
    asyncio.run(resumer.run_once())

    assert handled == ["good"]
    assert resumer.failed == 1
    assert asyncio.run(resumer.run_once()) == 0


def test_resumer_requires_history():
    with pytest.raises(ValueError):
        ApprovalResumer(object(), lambda entry: None)


def test_resumer_drains_a_burst_across_polls():
    entries = [
        _entry("req-old", minutes=0),
        _entry("req-mid", minutes=1),
        _entry("req-new", minutes=2),
    ]
    handled: list[str] = []

    async def handler(entry):
        handled.append(entry.request.request_id)

    resumer = ApprovalResumer(FakeInbox(entries), handler, batch=2)
    asyncio.run(resumer.run_once())
    asyncio.run(resumer.run_once())

    assert handled == ["req-old", "req-mid", "req-new"]


def test_resumer_skips_expired():
    handled: list[str] = []

    async def handler(entry):
        handled.append(entry.request.request_id)

    resumer = ApprovalResumer(
        FakeInbox([_entry("req-expired", status="expired"), _entry("req-ok")]), handler
    )
    asyncio.run(resumer.run_once())

    assert handled == ["req-ok"]
    assert resumer.handled == 1


def test_webhook_rejected_is_not_retried():
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = WebhookNotifier(
        "https://hook.example.test/approvals",
        secret="s3cret",  # pragma: allowlist secret
        client=client,
        retries=2,
        backoff_seconds=0,
    )
    with pytest.raises(NotifierError):
        asyncio.run(notifier.notify(_notice()))
    asyncio.run(client.aclose())
    assert len(attempts) == 1


def test_claim_dir_allows_one_winner(tmp_path):
    entries = [_entry("req-1")]
    handled: list[str] = []

    async def handler(entry):
        handled.append(entry.request.request_id)

    first = ApprovalResumer(FakeInbox(entries), handler, claim_dir=tmp_path)
    second = ApprovalResumer(FakeInbox(entries), handler, claim_dir=tmp_path)
    asyncio.run(first.run_once())
    asyncio.run(second.run_once())

    assert handled == ["req-1"]
    assert first.handled == 1
    assert second.handled == 0
    assert second.skipped == 1


def test_claim_rejects_unsafe_request_ids(tmp_path):
    inbox = FakeInbox([_entry("../escape")])
    resumer = ApprovalResumer(inbox, lambda entry: None, claim_dir=tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(resumer.run_once())


def test_runbook_documents_deferred_approvals():
    from pathlib import Path as _Path

    runbook = _Path(__file__).resolve().parents[1] / "docs" / "guides" / "deferred-approvals.md"
    text = runbook.read_text(encoding="utf-8")

    for phrase in ("ApprovalResumer", "claim_dir", "expires_at", "skipped", "Postgres"):
        assert phrase in text, phrase
    assert "单赢家" in text
