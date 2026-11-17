"""SLICE-049: the console hides and rejects expired approvals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.approvals import FileApprovalInbox
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
AUTH = {"Authorization": "Bearer alice-token"}
ALICE = Principal(tenant="acme", subject="alice", kind="human", roles=["operator"])


class Clock:
    def __init__(self, now: datetime = _AT) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Provider:
    async def resolve(self, credential: str) -> Principal:
        return ALICE


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _request(request_id: str, *, expires_at: datetime | None) -> ApprovalRequest:
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


def _inbox(tmp_path) -> FileApprovalInbox:
    return FileApprovalInbox(tmp_path, poll_seconds=0.01, clock=Clock())


def _app(inbox: FileApprovalInbox) -> TestClient:
    return TestClient(
        build_console_app(_agents(), auth_token=None, oidc=_Provider(), approvals=inbox)
    )


def test_decide_expired_returns_410(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request("req-1", expires_at=_AT - timedelta(hours=1)))

    with _app(inbox) as client:
        response = client.post(
            "/api/approvals/req-1",
            json={"approved": True},
            headers=AUTH,
        )

    assert response.status_code == 410
    assert response.json() == {"error": "approval_expired"}
    record = inbox.get("req-1")
    assert record is not None
    assert record.decision is None


def test_list_excludes_expired(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request("expired", expires_at=_AT - timedelta(hours=1)))
    inbox.submit(_request("valid", expires_at=_AT + timedelta(hours=1)))

    with _app(inbox) as client:
        response = client.get("/api/approvals", headers=AUTH)

    assert response.status_code == 200
    [item] = response.json()
    assert item["request_id"] == "valid"
    assert item["expires_at"] is not None


def _deadline(item: dict) -> datetime:
    return datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00"))


def test_list_materializes_the_ttl_deadline(tmp_path):
    inbox = FileApprovalInbox(tmp_path, clock=Clock(), ttl_seconds=300)
    inbox.submit(_request("req-1", expires_at=None))

    with _app(inbox) as client:
        [item] = client.get("/api/approvals", headers=AUTH).json()

    assert _deadline(item) == _AT + timedelta(seconds=300)


def test_list_keeps_an_explicit_deadline(tmp_path):
    explicit = _AT + timedelta(hours=2)
    inbox = FileApprovalInbox(tmp_path, clock=Clock(), ttl_seconds=300)
    inbox.submit(_request("req-1", expires_at=explicit))

    with _app(inbox) as client:
        [item] = client.get("/api/approvals", headers=AUTH).json()

    assert _deadline(item) == explicit


def test_list_without_ttl_or_deadline_stays_null(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request("req-1", expires_at=None))

    with _app(inbox) as client:
        [item] = client.get("/api/approvals", headers=AUTH).json()

    assert item["expires_at"] is None
