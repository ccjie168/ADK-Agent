"""SLICE-087: the control plane exposes connector registration."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from adk_agent.audit import ListAuditSink
from adk_agent.core import ConnectorSpec, Principal
from adk_agent.registry import FileConnectorStore
from adk_agent.registry.service import build_registry_service_app

AUTH = {"Authorization": "Bearer secret"}
OIDC_AUTH = {"Authorization": "Bearer token"}


class MemoryRegistry:
    async def publish(self, agent):
        return agent

    async def get(self, ref, tenant):
        return None

    async def list(self, tenant):
        return []

    async def tenants(self):
        return []


class FakeProvider:
    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self._principal


def _spec(**overrides) -> dict:
    data = {
        "connector_id": "crm",
        "tenant": "acme",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://crm/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
        "data_classes": ["internal"],
        "timeout_seconds": 10,
        "max_response_bytes": 1024,
    }
    data.update(overrides)
    return data


def _app(tmp_path, *, oidc=None, audit=None, connectors=True):
    return build_registry_service_app(
        MemoryRegistry(),
        connectors=FileConnectorStore(tmp_path / "connectors") if connectors else None,
        audit=audit,
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
    )


def test_list_visibility(tmp_path):
    store = FileConnectorStore(tmp_path / "connectors")
    asyncio.run(store.add(ConnectorSpec(**_spec())))
    asyncio.run(store.add(ConnectorSpec(**_spec(connector_id="shared", tenant=None))))
    asyncio.run(store.add(ConnectorSpec(**_spec(connector_id="other", tenant="other"))))

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/v1/connectors?tenant=acme", headers=AUTH)

    assert response.status_code == 200
    assert [item["connector_id"] for item in response.json()["connectors"]] == ["crm", "shared"]
    assert response.json()["count"] == 2


def test_register_and_audit(tmp_path):
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        response = client.post("/v1/connectors", json=_spec(), headers=AUTH)

    assert response.status_code == 201
    assert response.json()["connector_id"] == "crm"
    [event] = [item for item in sink.recent() if item.action == "connector.register"]
    assert event.status == "ok"
    assert event.target == "acme/crm"
    assert event.tenant == "acme"


def test_register_conflict(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/v1/connectors", json=_spec(), headers=AUTH).status_code == 201
        response = client.post(
            "/v1/connectors",
            json=_spec(base_url="https://other.example.com"),
            headers=AUTH,
        )

    assert response.status_code == 409
    assert response.json() == {"error": "connector_conflict"}


def test_non_admin_forbidden(tmp_path):
    provider = FakeProvider(Principal(tenant="acme", subject="alice", kind="human"))
    with TestClient(_app(tmp_path, oidc=provider)) as client:
        create = client.post("/v1/connectors", json=_spec(), headers=OIDC_AUTH)
        listed = client.get("/v1/connectors?tenant=other", headers=OIDC_AUTH)

    assert create.status_code == 403
    assert create.json() == {"error": "forbidden"}
    assert listed.status_code == 403
    assert listed.json() == {"error": "tenant_forbidden"}


def test_disable_idempotent(tmp_path):
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        assert client.post("/v1/connectors", json=_spec(), headers=AUTH).status_code == 201
        first = client.post("/v1/connectors/crm/disable", headers=AUTH)
        second = client.post("/v1/connectors/crm/disable", headers=AUTH)
        missing = client.post("/v1/connectors/missing/disable", headers=AUTH)

    assert first.status_code == 200
    assert first.json()["enabled"] is False
    assert second.status_code == 200
    assert second.json()["enabled"] is False
    assert missing.status_code == 404
    assert missing.json() == {"error": "connector_not_found"}
    actions = [item.action for item in sink.recent() if item.action == "connector.disable"]
    assert actions == ["connector.disable"]


def test_get_connector(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/v1/connectors", json=_spec(), headers=AUTH).status_code == 201
        found = client.get("/v1/connectors/crm", headers=AUTH)
        missing = client.get("/v1/connectors/nope", headers=AUTH)

    assert found.status_code == 200
    assert found.json()["base_url"] == "https://crm.example.com"
    assert missing.status_code == 404
    assert missing.json() == {"error": "connector_not_found"}


def test_store_not_configured(tmp_path):
    with TestClient(_app(tmp_path, connectors=False)) as client:
        listed = client.get("/v1/connectors?tenant=acme", headers=AUTH)
        created = client.post("/v1/connectors", json=_spec(), headers=AUTH)

    assert listed.status_code == 503
    assert listed.json() == {"error": "connector_store_unavailable"}
    assert created.status_code == 503


def test_invalid_connector(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/v1/connectors",
            json=_spec(base_url="http://example.com"),
            headers=AUTH,
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_connector"}
