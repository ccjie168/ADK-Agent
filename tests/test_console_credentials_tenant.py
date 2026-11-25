"""SLICE-283: credential routes reject an unsafe resolved tenant before storage."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import CredentialBinding, Principal
from adk_agent.identity import InvalidIdentity
from adk_agent.registry import FileCredentialStore

PRINCIPALS = {
    "unsafe-token": Principal(tenant="bad tenant", subject="alice", kind="human", roles=["admin"]),
    "safe-token": Principal(tenant="acme", subject="bob", kind="human", roles=["admin"]),
}
AUTH_UNSAFE = {"Authorization": "Bearer unsafe-token"}
AUTH_SAFE = {"Authorization": "Bearer safe-token"}


class _Provider:
    async def resolve(self, credential: str) -> Principal:
        principal = PRINCIPALS.get(credential)
        if principal is None:
            raise InvalidIdentity("invalid token")
        return principal


def _binding(tenant: str = "local") -> CredentialBinding:
    return CredentialBinding(
        credential_id="crm",
        tenant=tenant,
        secret_ref=f"secret://{tenant}/token",
        description="CRM token",
        created_by="seed",
        created_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
    )


def _app(tmp_path):
    store = FileCredentialStore(tmp_path / "credentials")
    asyncio.run(store.add(_binding()))
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token=None,
        oidc=_Provider(),
        credentials=store,
    )


def test_credentials_list_rejects_an_unsafe_caller_tenant(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/credentials", headers=AUTH_UNSAFE)
    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_tenant"}


def test_credentials_disable_rejects_an_unsafe_caller_tenant(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/credentials/crm/disable", headers=AUTH_UNSAFE)
    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_tenant"}


def test_credentials_list_rejects_an_unsafe_explicit_tenant(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/api/credentials", params={"tenant": "bad tenant"}, headers=AUTH_SAFE
        )
    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_tenant"}


def test_credentials_list_keeps_a_safe_tenant(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/credentials", headers=AUTH_SAFE)
    assert response.status_code == 200
    assert response.json() == []


def test_credentials_list_allows_admin_cross_tenant(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/credentials", params={"tenant": "local"}, headers=AUTH_SAFE)
    assert response.status_code == 200
    assert [item["tenant"] for item in response.json()] == ["local"]


def test_credentials_disable_rejects_an_unsafe_credential_id(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/credentials/bad%20name/disable", headers=AUTH_SAFE)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_credential"}


def test_credentials_disable_rejects_an_empty_tenant(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/credentials/crm/disable", params={"tenant": ""}, headers=AUTH_SAFE
        )
    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_tenant"}
