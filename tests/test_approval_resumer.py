"""SLICE-311: approval notices, the webhook notifier and the resumer."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

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


def _entry(request_id: str, status: str = "approved") -> ApprovalHistoryEntry:
    request = ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="ticket",
        agent_ref=AgentRef(id="ticket_writer", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant="local", subject="tester", kind="human"),
        input="x",
        requested_at=_NOW,
    )
    decision = ApprovalDecision(
        request_id=request_id,
        approved=status == "approved",
        approver="tester",
        decided_at=_NOW,
    )
    return ApprovalHistoryEntry(
        request=request, decision=decision, status=status, archived=False, terminal_at=_NOW
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

    def history(self, *, limit=50):
        self.polls += 1
        return self.entries[:limit]


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
