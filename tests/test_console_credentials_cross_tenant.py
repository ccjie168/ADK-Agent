"""SLICE-290: credential disable enforces the caller's tenant like the list does."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import CAPABILITIES_ALL, CredentialBinding, Principal, RoleDefinition
from adk_agent.identity import InvalidIdentity
from adk_agent.registry import FileCredentialStore, FileRoleStore

ADMIN_ROLE = RoleDefinition(
    name="admin",
    capabilities=tuple(sorted(CAPABILITIES_ALL)),
    description="full access",
)
ROLE = RoleDefinition(
    name="cred-admin",
    capabilities=("connectors.manage", "connectors.read"),
    description="credential operator without admin",
)
PRINCIPALS = {
    "cred-token": Principal(tenant="acme", subject="carol", kind="human", roles=["cred-admin"]),
    "admin-token": Principal(tenant="acme", subject="root", kind="human", roles=["admin"]),
}
AUTH_CRED = {"Authorization": "Bearer cred-token"}
AUTH_ADMIN = {"Authorization": "Bearer admin-token"}


class _Provider:
    async def resolve(self, credential: str) -> Principal:
        principal = PRINCIPALS.get(credential)
        if principal is None:
            raise InvalidIdentity("invalid token")
        return principal


def _binding(tenant: str, credential_id: str) -> CredentialBinding:
    return CredentialBinding(
        credential_id=credential_id,
        tenant=tenant,
        secret_ref=f"secret://{tenant}/token",
        created_by="seed",
        created_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
    )


def _app(tmp_path):
    credentials = FileCredentialStore(tmp_path / "credentials")
    asyncio.run(credentials.add(_binding("local", "crm")))
    asyncio.run(credentials.add(_binding("acme", "own")))
    roles = FileRoleStore(tmp_path / "roles")
    asyncio.run(roles.add(ADMIN_ROLE))
    asyncio.run(roles.add(ROLE))
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token=None,
        oidc=_Provider(),
        credentials=credentials,
        role_store=roles,
    )


def test_disable_rejects_a_cross_tenant_caller(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/credentials/crm/disable", params={"tenant": "local"}, headers=AUTH_CRED
        )
    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


def test_disable_allows_admin_cross_tenant(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/credentials/crm/disable", params={"tenant": "local"}, headers=AUTH_ADMIN
        )
    assert response.status_code == 200
    assert response.json()["credential_id"] == "crm"


def test_disable_keeps_the_own_tenant_path(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/credentials/own/disable", headers=AUTH_CRED)
    assert response.status_code == 200
    assert response.json()["credential_id"] == "own"


def test_list_still_rejects_a_cross_tenant_caller(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/credentials", params={"tenant": "local"}, headers=AUTH_CRED)
    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}
