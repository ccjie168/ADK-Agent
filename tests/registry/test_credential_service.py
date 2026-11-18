"""SLICE-142: the control plane encrypts credential values server-side."""

from __future__ import annotations

import asyncio
import os

from fastapi.testclient import TestClient

from adk_agent.audit import ListAuditSink
from adk_agent.core import Principal
from adk_agent.registry import FileCredentialStore
from adk_agent.registry.service import build_registry_service_app
from adk_agent.secretstore import LocalKeyBackend, credential_aad

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


def _body(**overrides) -> dict:
    body = {
        "tenant": "acme",
        "credential_id": "crm",
        "secret_ref": "secret://acme/token",
        "description": "CRM token",
    }
    body.update(overrides)
    return body


def _app(tmp_path, *, oidc=None, audit=None, credentials=True, backend=True):
    return build_registry_service_app(
        MemoryRegistry(),
        credentials=FileCredentialStore(tmp_path / "credentials") if credentials else None,
        key_backend=LocalKeyBackend({"k1": os.urandom(32)}, "k1") if backend else None,
        audit=audit,
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
    )


def test_register_encrypts_a_plaintext_secret(tmp_path):
    sink = ListAuditSink()
    store = FileCredentialStore(tmp_path / "credentials")
    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")

    def build():
        return build_registry_service_app(
            MemoryRegistry(),
            credentials=store,
            key_backend=backend,
            audit=sink,
            auth_token="secret",
        )

    with TestClient(build()) as client:
        response = client.post("/v1/credentials", json=_body(secret="tok-123"), headers=AUTH)

    assert response.status_code == 201
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["secret_key_id"] == "k1"
    assert payload["secret_version"] == 1
    assert "wrapped_secret" not in payload
    stored = asyncio.run(store.get("acme", "crm"))
    assert stored is not None
    assert stored.wrapped_secret is not None
    assert backend.unwrap(stored.wrapped_secret, credential_aad("acme", "crm")) == b"tok-123"
    [event] = [item for item in sink.recent() if item.action == "credential.register"]
    assert event.target == "acme/crm"
    assert event.agent_ref.version == "credential.k1"
    assert "tok-123" not in event.model_dump_json()


def test_register_metadata_only(tmp_path):
    with TestClient(_app(tmp_path, backend=False)) as client:
        response = client.post("/v1/credentials", json=_body(), headers=AUTH)

    assert response.status_code == 201
    assert response.json()["secret_key_id"] is None
    assert response.json()["secret_version"] is None


def test_register_secret_needs_a_key_backend(tmp_path):
    with TestClient(_app(tmp_path, backend=False)) as client:
        response = client.post("/v1/credentials", json=_body(secret="tok"), headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"error": "key_backend_unavailable"}


def test_register_rejects_ciphertext_in_the_body(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/v1/credentials", json=_body(wrapped_secret={"v": 1}), headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_credential"}


def test_register_rejects_multiline_or_empty_secrets(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        multiline = client.post("/v1/credentials", json=_body(secret="a\r\nb"), headers=AUTH)
        empty = client.post("/v1/credentials", json=_body(secret=""), headers=AUTH)
        oversized = client.post("/v1/credentials", json=_body(secret="x" * 8193), headers=AUTH)

    for response in (multiline, empty, oversized):
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_credential"}


def test_register_requires_admin(tmp_path):
    provider = FakeProvider(
        Principal(tenant="acme", subject="alice", kind="human", roles=["operator"])
    )
    with TestClient(_app(tmp_path, oidc=provider)) as client:
        response = client.post("/v1/credentials", json=_body(), headers=OIDC_AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_disable_is_idempotent_and_audited(tmp_path):
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        assert (
            client.post("/v1/credentials", json=_body(secret="tok"), headers=AUTH).status_code
            == 201
        )
        first = client.post("/v1/credentials/crm/disable?tenant=acme", headers=AUTH)
        second = client.post("/v1/credentials/crm/disable?tenant=acme", headers=AUTH)
        missing = client.post("/v1/credentials/missing/disable?tenant=acme", headers=AUTH)

    assert first.status_code == 200
    assert first.json()["enabled"] is False
    assert second.status_code == 200
    assert missing.status_code == 404
    assert missing.json() == {"error": "credential_not_found"}
    events = [item for item in sink.recent() if item.action == "credential.disable"]
    assert len(events) == 1
    assert events[0].target == "acme/crm"


def test_credential_store_unavailable_when_not_configured(tmp_path):
    with TestClient(_app(tmp_path, credentials=False)) as client:
        registered = client.post("/v1/credentials", json=_body(), headers=AUTH)
        disabled = client.post("/v1/credentials/crm/disable?tenant=acme", headers=AUTH)

    for response in (registered, disabled):
        assert response.status_code == 503
        assert response.json() == {"error": "credential_store_unavailable"}


def test_disable_needs_a_tenant_without_oidc(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/v1/credentials/crm/disable", headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}
