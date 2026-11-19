"""SLICE-122: console connector request routes and approval flow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import ConnectorRequest, ConnectorSpec
from adk_agent.registry import (
    FileConnectorRequestStore,
    FileConnectorStore,
    FileCredentialStore,
)

AUTH = {"Authorization": "Bearer secret"}
_NOW = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)


def _credential(ref: str = "secret://local/token", **overrides):
    body = {
        "credential_id": "crm",
        "tenant": "local",
        "description": "CRM token",
        "created_by": "client",
        "created_at": "2026-11-16T08:00:00Z",
    }
    body["secret_ref"] = ref
    body.update(overrides)
    return body


def _spec(**overrides):
    body = {
        "connector_id": "crm",
        "tenant": "local",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://local/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
        "data_classes": ["internal"],
    }
    body.update(overrides)
    return body


def _request_body(**overrides):
    body = {"spec": _spec(), "reason": "Need CRM read access"}
    body.update(overrides)
    return body


def _record(tenant: str, request_id: str) -> ConnectorRequest:
    return ConnectorRequest(
        request_id=request_id,
        tenant=tenant,
        spec=ConnectorSpec.model_validate(
            {
                "connector_id": "crm",
                "tenant": tenant,
                "kind": "http",
                "base_url": "https://crm.example.com",
                "methods": ["GET"],
                "path_prefixes": ["/v1/crm/"],
            }
        ),
        reason="seed",
        requested_by="alice",
        requested_at=_NOW,
    )


def _app(
    tmp_path, *, roles=("admin",), connectors=True, credentials=True, requests=True, audit=None
):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        connectors=FileConnectorStore(tmp_path / "connectors") if connectors else None,
        credentials=FileCredentialStore(tmp_path / "credentials") if credentials else None,
        connector_requests=(FileConnectorRequestStore(tmp_path / "requests") if requests else None),
        audit_sink=audit,
    )


def test_panel_is_rendered(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert 'id="connector-requests-body"' in page.text
    assert 'id="connector-request-submit"' in page.text
    assert 'id="connector-request-approve"' in page.text


def test_request_and_approve_registers_connector(tmp_path):
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        assert client.post("/api/credentials", json=_credential(), headers=AUTH).status_code == 201
        requested = client.post("/api/connector-requests", json=_request_body(), headers=AUTH)
        request_id = requested.json()["request_id"]
        decided = client.post(
            f"/api/connector-requests/{request_id}/decide",
            json={"approved": True, "reason": "ok"},
            headers=AUTH,
        )
        listed = client.get("/api/connectors?tenant=local", headers=AUTH)
        requests = client.get("/api/connector-requests?tenant=local", headers=AUTH)

    assert requested.status_code == 201
    assert requested.json()["status"] == "pending"
    assert requested.json()["requested_by"] == "console_user"
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["registered_connector"] == "crm"
    assert [item["connector_id"] for item in listed.json()] == ["crm"]
    assert [item["request_id"] for item in requests.json()] == [request_id]
    actions = [event.action for event in sink.recent()]
    assert "connector.request" in actions
    assert "connector.register" in actions
    assert "connector.request.decide" in actions


def test_approve_requires_enabled_binding(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        requested = client.post("/api/connector-requests", json=_request_body(), headers=AUTH)
        request_id = requested.json()["request_id"]
        decided = client.post(
            f"/api/connector-requests/{request_id}/decide",
            json={"approved": True},
            headers=AUTH,
        )
        still = client.get("/api/connector-requests?tenant=local", headers=AUTH)

    assert decided.status_code == 400
    assert decided.json() == {"error": "credential_unbound"}
    assert [item["status"] for item in still.json()] == ["pending"]


def test_deny_does_not_register(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        requested = client.post("/api/connector-requests", json=_request_body(), headers=AUTH)
        request_id = requested.json()["request_id"]
        decided = client.post(
            f"/api/connector-requests/{request_id}/decide",
            json={"approved": False, "reason": "not needed"},
            headers=AUTH,
        )
        listed = client.get("/api/connectors?tenant=local", headers=AUTH)

    assert decided.status_code == 200
    assert decided.json()["status"] == "denied"
    assert decided.json()["registered_connector"] is None
    assert listed.json() == []


def test_decide_requires_admin(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        requested = client.post("/api/connector-requests", json=_request_body(), headers=AUTH)
        request_id = requested.json()["request_id"]
        decided = client.post(
            f"/api/connector-requests/{request_id}/decide",
            json={"approved": True},
            headers=AUTH,
        )

    assert decided.status_code == 403
    assert decided.json() == {"error": "forbidden"}


def test_list_filters_by_tenant(tmp_path):
    asyncio.run(FileConnectorRequestStore(tmp_path / "requests").add(_record("acme", "acme-req")))
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/connector-requests", json=_request_body(), headers=AUTH)
        local = client.get("/api/connector-requests?tenant=local", headers=AUTH)
        acme = client.get("/api/connector-requests?tenant=acme", headers=AUTH)
        invalid = client.get("/api/connector-requests?tenant=local&status=bogus", headers=AUTH)

    assert {item["tenant"] for item in local.json()} == {"local"}
    assert [item["request_id"] for item in acme.json()] == ["acme-req"]
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "invalid_status"}


def test_deciding_twice_conflicts(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/credentials", json=_credential(), headers=AUTH)
        requested = client.post("/api/connector-requests", json=_request_body(), headers=AUTH)
        request_id = requested.json()["request_id"]
        first = client.post(
            f"/api/connector-requests/{request_id}/decide",
            json={"approved": True},
            headers=AUTH,
        )
        second = client.post(
            f"/api/connector-requests/{request_id}/decide",
            json={"approved": False},
            headers=AUTH,
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"error": "connector_request_already_decided"}


def test_read_requires_capability(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = client.get("/api/connector-requests", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_operator_can_read_requests(tmp_path):
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        response = client.get("/api/connector-requests", headers=AUTH)

    assert response.status_code == 200
