"""SLICE-118: the console approval history API and panel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.approvals import FileApprovalInbox
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, ApprovalRequest, Principal
from adk_agent.identity import InvalidIdentity

UTC = timezone.utc
NOW = datetime(2026, 11, 16, 10, 0, 0, tzinfo=UTC)

ALICE = Principal(tenant="acme", subject="alice", kind="human")
LOCAL_VIEWER = Principal(tenant="local", subject="local-viewer", kind="human", roles=["viewer"])
ADMIN = Principal(tenant="acme", subject="admin", kind="human", roles=["admin"])

TOKENS = {
    "alice-token": ALICE,
    "local-token": LOCAL_VIEWER,
    "admin-token": ADMIN,
}

AUTH_ALICE = {"Authorization": "Bearer alice-token"}
AUTH_LOCAL = {"Authorization": "Bearer local-token"}
AUTH_ADMIN = {"Authorization": "Bearer admin-token"}


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Provider:
    async def resolve(self, credential: str) -> Principal:
        principal = TOKENS.get(credential)
        if principal is None:
            raise InvalidIdentity("invalid token")
        return principal


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _request(
    request_id: str,
    *,
    tenant: str = "acme",
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
        requested_at=NOW,
        expires_at=expires_at,
    )


def _inbox(tmp_path, *, clock: Clock | None = None) -> FileApprovalInbox:
    return FileApprovalInbox(tmp_path / "inbox", clock=clock or Clock())


def _app(*, approvals: FileApprovalInbox | None) -> TestClient:
    return TestClient(
        build_console_app(
            _agents(),
            auth_token=None,
            oidc=_Provider(),
            approvals=approvals,
        )
    )


def test_history_lists_decided_entries(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock=clock)
    future = NOW + timedelta(hours=1)
    inbox.submit(_request("req-a", expires_at=future))
    inbox.submit(_request("req-b", expires_at=future))
    clock.now = NOW + timedelta(minutes=1)
    inbox.decide("req-a", approved=True, approver="alice", reason="ok")
    clock.now = NOW + timedelta(minutes=2)
    inbox.decide("req-b", approved=False, approver="bob", reason="no")

    with _app(approvals=inbox) as client:
        response = client.get("/api/approvals/history", headers=AUTH_ALICE)

    assert response.status_code == 200
    body = response.json()
    assert [item["request"]["request_id"] for item in body] == ["req-b", "req-a"]
    assert [item["status"] for item in body] == ["denied", "approved"]
    denied = body[0]
    assert denied["decision"]["approver"] == "bob"
    assert denied["decision"]["reason"] == "no"
    assert denied["archived"] is False
    assert denied["terminal_at"].startswith("2026-11-16T10:02:00")
    assert body[1]["decision"]["approved"] is True


def test_history_filters_by_tenant(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock=clock)
    future = NOW + timedelta(hours=1)
    inbox.submit(_request("local-1", tenant="local", expires_at=future))
    inbox.submit(_request("other-1", tenant="other", expires_at=future))
    inbox.decide("local-1", approved=True, approver="alice")
    inbox.decide("other-1", approved=True, approver="carol")

    with _app(approvals=inbox) as client:
        local = client.get("/api/approvals/history", headers=AUTH_LOCAL)
        admin = client.get("/api/approvals/history", headers=AUTH_ADMIN)

    assert [item["request"]["request_id"] for item in local.json()] == ["local-1"]
    assert {item["request"]["request_id"] for item in admin.json()} == {"local-1", "other-1"}


def test_history_rejects_unknown_status(tmp_path):
    inbox = _inbox(tmp_path)
    with _app(approvals=inbox) as client:
        response = client.get("/api/approvals/history?status=pending", headers=AUTH_ALICE)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_status"}


def test_history_limit_is_clamped(tmp_path):
    clock = Clock()
    inbox = _inbox(tmp_path, clock=clock)
    future = NOW + timedelta(hours=1)
    for request_id in ("r0", "r1", "r2"):
        inbox.submit(_request(request_id, expires_at=future))
    for request_id, minute in (("r0", 1), ("r1", 2), ("r2", 3)):
        clock.now = NOW + timedelta(minutes=minute)
        inbox.decide(request_id, approved=True, approver="alice")

    with _app(approvals=inbox) as client:
        one = client.get("/api/approvals/history?limit=1", headers=AUTH_ALICE)
        zero = client.get("/api/approvals/history?limit=0", headers=AUTH_ALICE)

    assert [item["request"]["request_id"] for item in one.json()] == ["r2"]
    assert [item["request"]["request_id"] for item in zero.json()] == ["r2"]


def test_history_not_configured():
    with _app(approvals=None) as client:
        response = client.get("/api/approvals/history", headers=AUTH_ALICE)

    assert response.status_code == 404
    assert response.json() == {"error": "approvals_not_configured"}


def test_page_has_approval_history_block():
    with _app(approvals=None) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert 'id="approval-history-body"' in page.text
    assert 'id="refresh-approval-history"' in page.text
    assert 'id="approval-history-status"' in page.text
