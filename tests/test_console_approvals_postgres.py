"""SLICE-099: the console awaits an async approval inbox and maps 503."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.approvals import ApprovalRecord
from adk_agent.approvals_postgres import ApprovalInboxUnavailable
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, ApprovalDecision, ApprovalRequest, Principal
from adk_agent.identity import InvalidIdentity

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)

ALICE = Principal(tenant="acme", subject="alice", kind="human", roles=["admin"])

TOKENS = {"alice-token": ALICE}


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


def _request(request_id: str = "req-1") -> ApprovalRequest:
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
    )


class AsyncInbox:
    def __init__(self, request: ApprovalRequest | None = None) -> None:
        self._request = request
        self.decided: ApprovalDecision | None = None

    async def pending(self) -> list[ApprovalRequest]:
        return [self._request] if self._request is not None else []

    async def get(self, request_id: str) -> ApprovalRecord | None:
        if self._request is None or self._request.request_id != request_id:
            return None
        return ApprovalRecord(request=self._request, decision=self.decided)

    async def decide(
        self, request_id: str, *, approved: bool, approver: str, reason: str = ""
    ) -> ApprovalDecision:
        assert request_id == self._request.request_id
        self.decided = ApprovalDecision(
            request_id=request_id,
            approved=approved,
            approver=approver,
            reason=reason,
            decided_at=datetime.now(UTC),
        )
        return self.decided


class UnavailableInbox:
    async def pending(self) -> list[ApprovalRequest]:
        raise ApprovalInboxUnavailable("db down")

    async def get(self, request_id: str) -> ApprovalRecord | None:
        raise ApprovalInboxUnavailable("db down")

    async def decide(
        self, request_id: str, *, approved: bool, approver: str, reason: str = ""
    ) -> ApprovalDecision:
        raise ApprovalInboxUnavailable("db down")


def _client(*, approvals) -> TestClient:
    return TestClient(
        build_console_app(
            _agents(),
            auth_token=None,
            oidc=_Provider(),
            approvals=approvals,
        )
    )


def test_console_awaits_async_inbox():
    request = _request()
    inbox = AsyncInbox(request)
    with _client(approvals=inbox) as client:
        listing = client.get("/api/approvals", headers={"Authorization": "Bearer alice-token"})
        decision = client.post(
            "/api/approvals/req-1",
            json={"approved": True, "reason": "ok"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert listing.status_code == 200
    assert [item["request_id"] for item in listing.json()] == ["req-1"]

    assert decision.status_code == 200
    body = decision.json()
    assert body["approved"] is True
    assert body["approver"] == "alice"
    assert body["reason"] == "ok"
    assert inbox.decided is not None
    assert inbox.decided.approver == "alice"


def test_console_maps_unavailable_to_503():
    inbox = UnavailableInbox()
    with _client(approvals=inbox) as client:
        listing = client.get("/api/approvals", headers={"Authorization": "Bearer alice-token"})
        decision = client.post(
            "/api/approvals/req-1",
            json={"approved": True},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert listing.status_code == 503
    assert listing.json() == {"error": "approval_unavailable"}
    assert decision.status_code == 503
    assert decision.json() == {"error": "approval_unavailable"}
