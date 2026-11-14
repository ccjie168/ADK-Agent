"""SLICE-087: the console lists, registers and disables connectors."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.registry import FileConnectorStore

AUTH = {"Authorization": "Bearer secret"}


def _body(**overrides):
    body = {
        "connector_id": "crm",
        "tenant": "local",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://crm/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
        "data_classes": ["internal"],
        "timeout_seconds": 10,
        "max_response_bytes": 1024,
    }
    body.update(overrides)
    return body


def _app(tmp_path, *, roles=None, connectors=True, audit=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        connectors=FileConnectorStore(tmp_path / "connectors") if connectors else None,
        audit_sink=audit,
    )


def test_list_and_register(tmp_path):
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        created = client.post("/api/connectors", json=_body(), headers=AUTH)
        listed = client.get("/api/connectors?tenant=local", headers=AUTH)

    assert created.status_code == 201
    assert created.json()["connector_id"] == "crm"
    assert [item["connector_id"] for item in listed.json()] == ["crm"]
    [event] = [item for item in sink.recent() if item.action == "connector.register"]
    assert event.target == "local/crm"
    assert event.tenant == "local"


def test_disable_idempotent(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/connectors", json=_body(), headers=AUTH).status_code == 201
        first = client.post("/api/connectors/crm/disable", headers=AUTH)
        second = client.post("/api/connectors/crm/disable", headers=AUTH)
        missing = client.post("/api/connectors/missing/disable", headers=AUTH)

    assert first.status_code == 200
    assert first.json()["enabled"] is False
    assert second.status_code == 200
    assert missing.status_code == 404
    assert missing.json() == {"error": "connector_not_found"}


def test_non_admin_forbidden(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        created = client.post("/api/connectors", json=_body(), headers=AUTH)
        disabled = client.post("/api/connectors/crm/disable", headers=AUTH)

    assert created.status_code == 403
    assert created.json() == {"error": "forbidden"}
    assert disabled.status_code == 403


def test_not_configured(tmp_path):
    with TestClient(_app(tmp_path, connectors=False)) as client:
        listed = client.get("/api/connectors?tenant=local", headers=AUTH)
        created = client.post("/api/connectors", json=_body(), headers=AUTH)

    assert listed.status_code == 404
    assert listed.json() == {"error": "connectors_not_configured"}
    assert created.status_code == 404


def test_invalid_connector(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/connectors",
            json=_body(base_url="http://example.com"),
            headers=AUTH,
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_connector"}
