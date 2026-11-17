"""SLICE-081: console request, list and decide endpoints for tool grants."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentManifest, ToolGrantRequest
from adk_agent.registry import (
    FileAgentLifecycleStore,
    FileAgentRegistry,
    FileToolGrantStore,
    published_from,
)

AUTH = {"Authorization": "Bearer secret"}


def _manifest(tenant: str = "acme") -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant=tenant,
        owner=tenant,
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _record(tmp_path, tenant: str = "acme"):
    registry = FileAgentRegistry(tmp_path / "registry")
    record = published_from(_manifest(tenant))
    asyncio.run(registry.publish(record))
    return registry, record


def _app(tmp_path, *, tenant="acme", roles=None, grants=True, audit=None):
    registry, _record_value = _record(tmp_path, tenant)
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        registry=registry,
        lifecycle=FileAgentLifecycleStore(tmp_path / "registry"),
        tool_grants=FileToolGrantStore(tmp_path / "grants") if grants else None,
        audit_sink=audit,
    )


def _body(record, **overrides):
    body = {
        "tenant": record.manifest.tenant,
        "agent_id": record.manifest.id,
        "version": record.manifest.version,
        "digest": record.digest,
        "tool_id": "crm.read",
        "data_classes": ["internal"],
        "reason": "temporary access",
        "expires_hours": 4,
    }
    body.update(overrides)
    return body


def _request(client, record, **overrides):
    return client.post("/api/tool-grants", json=_body(record, **overrides), headers=AUTH)


def test_request_and_list(tmp_path):
    registry, record = _record(tmp_path)
    with TestClient(_app(tmp_path)) as client:
        created = _request(client, record)
        listed = client.get("/api/tool-grants?tenant=acme", headers=AUTH)

    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    assert created.json()["requested_by"] == "console_user"
    assert listed.status_code == 200
    assert [item["request_id"] for item in listed.json()] == [created.json()["request_id"]]


def test_request_requires_published_version(tmp_path):
    _registry, record = _record(tmp_path)
    with TestClient(_app(tmp_path)) as client:
        missing = _request(client, record, version="9.9.9")
        wrong_digest = _request(client, record, digest="sha256:" + "0" * 64)

    assert missing.status_code == 404
    assert missing.json() == {"error": "not_found"}
    assert wrong_digest.status_code == 404


def test_retired_version_rejected(tmp_path):
    _registry, record = _record(tmp_path)
    asyncio.run(
        FileAgentLifecycleStore(tmp_path / "registry").set(
            "acme", "bot", "1.0.0", status="retired", changed_by="ops", reason="stop"
        )
    )
    with TestClient(_app(tmp_path)) as client:
        response = _request(client, record)

    assert response.status_code == 409
    assert response.json() == {"error": "version_retired"}


def test_cross_tenant_forbidden(tmp_path):
    _registry, record = _record(tmp_path, tenant="acme")
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = _request(client, record)

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


def test_non_admin_cannot_decide(tmp_path):
    _registry, record = _record(tmp_path, tenant="local")
    with TestClient(_app(tmp_path, tenant="local", roles=["viewer"])) as client:
        created = _request(client, record)
        response = client.post(
            f"/api/tool-grants/{created.json()['request_id']}/decide",
            json={"approved": True, "reason": "ok"},
            headers=AUTH,
        )

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_decide_and_audit(tmp_path):
    registry, record = _record(tmp_path)
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        created = _request(client, record)
        decided = client.post(
            f"/api/tool-grants/{created.json()['request_id']}/decide",
            json={"approved": True, "reason": "ok"},
            headers=AUTH,
        )

    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    actions = [event.action for event in sink.recent()]
    assert "tool_grant.request" in actions
    assert "tool_grant.decide" in actions


def test_decide_terminal_and_expired(tmp_path):
    registry, record = _record(tmp_path)
    store = FileToolGrantStore(tmp_path / "grants")
    now = datetime.now(timezone.utc)
    expired = ToolGrantRequest(
        request_id="expired1",
        tenant="acme",
        agent_id="bot",
        version="1.0.0",
        digest=record.digest,
        tool_id="crm.read",
        reason="old",
        requested_by="alice",
        requested_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    asyncio.run(store.add(expired))
    with TestClient(_app(tmp_path)) as client:
        created = _request(client, record)
        first = client.post(
            f"/api/tool-grants/{created.json()['request_id']}/decide",
            json={"approved": True, "reason": "ok"},
            headers=AUTH,
        )
        again = client.post(
            f"/api/tool-grants/{created.json()['request_id']}/decide",
            json={"approved": False, "reason": "no"},
            headers=AUTH,
        )
        late = client.post(
            "/api/tool-grants/expired1/decide",
            json={"approved": True, "reason": "late"},
            headers=AUTH,
        )

    assert first.status_code == 200
    assert again.status_code == 409
    assert again.json() == {"error": "grant_already_decided"}
    assert late.status_code == 410
    assert late.json() == {"error": "grant_expired"}


def test_no_store(tmp_path):
    with TestClient(_app(tmp_path, grants=False)) as client:
        response = client.get("/api/tool-grants?tenant=acme", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "tool_grants_not_configured"}


def test_read_requires_capability(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        listed = client.get("/api/tool-grants", headers=AUTH)
        usage = client.get("/api/tool-grants/usage", headers=AUTH)

    assert listed.status_code == 403
    assert listed.json() == {"error": "forbidden"}
    assert usage.status_code == 403
    assert usage.json() == {"error": "forbidden"}


def test_operator_can_read_grants(tmp_path):
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        listed = client.get("/api/tool-grants", headers=AUTH)
        usage = client.get("/api/tool-grants/usage", headers=AUTH)

    assert listed.status_code == 200
    assert usage.status_code == 200
