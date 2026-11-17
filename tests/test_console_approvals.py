"""SLICE-045: the console approval inbox API."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.approvals import FileApprovalInbox
from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, ApprovalRequest, Principal
from adk_agent.identity import InvalidIdentity

UTC = timezone.utc
_AT = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)

ALICE = Principal(tenant="acme", subject="alice", kind="human", roles=["operator"])
VIEWER = Principal(tenant="acme", subject="viewer", kind="human", roles=["operator"])
ADMIN = Principal(tenant="acme", subject="admin", kind="human", roles=["admin"])
CAROL = Principal(tenant="other", subject="carol", kind="human", roles=["operator"])
PUBLISHER = Principal(tenant="acme", subject="publisher", kind="human", roles=["publisher"])

TOKENS = {
    "alice-token": ALICE,
    "viewer-token": VIEWER,
    "admin-token": ADMIN,
    "carol-token": CAROL,
    "publisher-token": PUBLISHER,
}

AUTH_ALICE = {"Authorization": "Bearer alice-token"}
AUTH_VIEWER = {"Authorization": "Bearer viewer-token"}
AUTH_ADMIN = {"Authorization": "Bearer admin-token"}
AUTH_CAROL = {"Authorization": "Bearer carol-token"}
AUTH_PUBLISHER = {"Authorization": "Bearer publisher-token"}


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


def _request(request_id: str = "req-1", *, tenant: str = "acme", input_text="deploy prod"):
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


def _app(*, approvals: FileApprovalInbox | None, policy_file=None, audit=None) -> TestClient:
    return TestClient(
        build_console_app(
            _agents(),
            auth_token=None,
            oidc=_Provider(),
            approvals=approvals,
            policy_file=policy_file,
            audit_sink=audit,
        )
    )


def _inbox(tmp_path) -> FileApprovalInbox:
    return FileApprovalInbox(tmp_path / "inbox", poll_seconds=0.01)


def _decide(client, request_id="req-1", headers=AUTH_ALICE, payload=None):
    return client.post(
        f"/api/approvals/{request_id}",
        json=payload or {"approved": True, "reason": "ok"},
        headers=headers,
    )


def _policy_file(tmp_path, *, allow: list[str]):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "version": "1",
                "bindings": [{"role": "viewer", "tenant": "acme", "allow": allow}],
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_approvals_not_configured(tmp_path):
    with _app(approvals=None) as client:
        listing = client.get("/api/approvals", headers=AUTH_ALICE)
        deciding = _decide(client)

    assert listing.status_code == 404
    assert listing.json() == {"error": "approvals_not_configured"}
    assert deciding.status_code == 404
    assert deciding.json() == {"error": "approvals_not_configured"}


def test_list_pending_filters_by_tenant(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request("acme-1", tenant="acme"))
    inbox.submit(_request("other-1", tenant="other"))
    with _app(approvals=inbox) as client:
        alice = client.get("/api/approvals", headers=AUTH_ALICE)
        carol = client.get("/api/approvals", headers=AUTH_CAROL)

    assert [item["request_id"] for item in alice.json()] == ["acme-1"]
    assert [item["request_id"] for item in carol.json()] == ["other-1"]


def test_admin_sees_all_tenants(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request("acme-1", tenant="acme"))
    inbox.submit(_request("other-1", tenant="other"))
    with _app(approvals=inbox) as client:
        response = client.get("/api/approvals", headers=AUTH_ADMIN)

    assert {item["request_id"] for item in response.json()} == {"acme-1", "other-1"}


def test_decide_records_approver_and_audit(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())
    audit = ListAuditSink()
    with _app(approvals=inbox, audit=audit) as client:
        response = _decide(client, payload={"approved": True, "reason": "looks fine"})

    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is True
    assert body["approver"] == "alice"
    assert body["reason"] == "looks fine"

    record = inbox.get("req-1")
    assert record is not None
    assert record.decision is not None
    assert record.decision.approver == "alice"

    [event] = [e for e in audit.recent(10) if e.action == "approval.decide"]
    assert event.status == "ok"
    assert event.approver == "alice"
    assert event.target == "req-1"


def test_audit_has_no_input(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request(input_text="deploy prod"))
    audit = ListAuditSink()
    with _app(approvals=inbox, audit=audit) as client:
        _decide(client)

    [event] = [e for e in audit.recent(10) if e.action == "approval.decide"]
    assert event.args_hash is None
    assert "deploy prod" not in event.model_dump_json()


def test_decide_other_tenant_forbidden(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request(tenant="other"))
    with _app(approvals=inbox) as client:
        response = _decide(client, headers=AUTH_ALICE)

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}
    assert len(inbox.pending()) == 1


def test_decide_twice_conflicts(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())
    with _app(approvals=inbox) as client:
        first = _decide(client)
        second = _decide(client, payload={"approved": False})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"error": "approval_already_decided"}


def test_decide_unknown(tmp_path):
    inbox = _inbox(tmp_path)
    with _app(approvals=inbox) as client:
        response = _decide(client, "missing")

    assert response.status_code == 404
    assert response.json() == {"error": "approval_not_found"}


def test_unsafe_request_id(tmp_path):
    inbox = _inbox(tmp_path)
    with _app(approvals=inbox) as client:
        response = _decide(client, "bad$id")

    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_request_id"}


def test_policy_denies_decision(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())
    audit = ListAuditSink()
    policy = _policy_file(tmp_path, allow=["approval.read:*"])
    with _app(approvals=inbox, policy_file=policy, audit=audit) as client:
        response = _decide(client, headers=AUTH_VIEWER)

    assert response.status_code == 403
    assert response.json() == {"error": "policy_denied"}
    assert len(inbox.pending()) == 1
    [event] = [e for e in audit.recent(10) if e.action == "approval.decide"]
    assert event.status == "denied"
    assert event.error_code == "policy_denied"


def test_invalid_decision_body(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())
    with _app(approvals=inbox) as client:
        response = _decide(client, payload={"approved": "yes"})

    assert response.status_code == 400
    assert response.json() == {"error": "invalid decision"}


def test_approvals_require_a_token(tmp_path):
    inbox = _inbox(tmp_path)
    with _app(approvals=inbox) as client:
        assert client.get("/api/approvals").status_code == 401


def test_roles_without_approval_capabilities_are_forbidden(tmp_path):
    inbox = _inbox(tmp_path)
    inbox.submit(_request())
    with _app(approvals=inbox) as client:
        listed = client.get("/api/approvals", headers=AUTH_PUBLISHER)
        decided = _decide(client, headers=AUTH_PUBLISHER)
        history = client.get("/api/approvals/history", headers=AUTH_PUBLISHER)

    assert listed.status_code == 403
    assert listed.json() == {"error": "forbidden"}
    assert decided.status_code == 403
    assert decided.json() == {"error": "forbidden"}
    assert history.status_code == 403
    assert len(inbox.pending()) == 1
