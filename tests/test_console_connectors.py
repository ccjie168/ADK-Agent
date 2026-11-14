"""SLICE-087: the console lists, registers and disables connectors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import ConnectorSpec
from adk_agent.registry import ConnectorHealth, FileConnectorStore

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


HEALTH = ConnectorHealth(
    connector_id="crm",
    status="healthy",
    status_code=200,
    latency_ms=12,
    checked_at=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
)


def _seed(tmp_path, **overrides):
    spec = ConnectorSpec.model_validate(_body(**overrides))
    asyncio.run(FileConnectorStore(tmp_path / "connectors").add(spec))


def test_check_admin_only(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr(
        "adk_agent.console.check_connector",
        lambda spec: (_ for _ in ()).throw(AssertionError("probe ran for a non-admin")),
    )
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = client.post("/api/connectors/crm/check", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_check_missing_and_tenant(tmp_path):
    _seed(tmp_path, connector_id="foreign", tenant="acme")
    with TestClient(_app(tmp_path)) as client:
        missing = client.post("/api/connectors/missing/check", headers=AUTH)
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        foreign = client.post("/api/connectors/foreign/check", headers=AUTH)

    assert missing.status_code == 404
    assert missing.json() == {"error": "connector_not_found"}
    assert foreign.status_code == 403
    assert foreign.json() == {"error": "tenant_forbidden"}


def test_check_healthy(tmp_path, monkeypatch):
    async def fake_check(spec, *, client=None, max_timeout=5.0):
        return HEALTH

    monkeypatch.setattr("adk_agent.console.check_connector", fake_check)
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/connectors", json=_body(), headers=AUTH).status_code == 201
        response = client.post("/api/connectors/crm/check", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == HEALTH.model_dump(mode="json")
