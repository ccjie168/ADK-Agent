"""SLICE-261: role definition and user binding management endpoints."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import CAPABILITIES_ALL, RoleDefinition, seed_builtin_roles
from adk_agent.registry import FileRoleStore, FileUserBindingStore

AUTH = {"Authorization": "Bearer secret"}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _client(
    tmp_path: Path,
    *,
    roles: list[str],
    with_store: bool = True,
    with_bindings: bool = True,
):
    role_store = None
    if with_store:
        role_store = FileRoleStore(tmp_path / "roles")
        for role in seed_builtin_roles():
            asyncio.run(role_store.add(role))
    binding_store = FileUserBindingStore(tmp_path / "users") if with_bindings else None
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=roles,
        role_store=role_store,
        user_binding_store=binding_store,
    )
    return TestClient(app), role_store, binding_store


def test_roles_list_requires_capability(tmp_path):
    client, _, _ = _client(tmp_path, roles=["operator"])
    with client:
        response = client.get("/api/roles", headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_admin_defines_role_and_audits(tmp_path):
    client, store, _ = _client(tmp_path, roles=["admin"])
    with client:
        put = client.put(
            "/api/roles/qa",
            headers=AUTH,
            content=json.dumps({"capabilities": ["tools.read"], "description": "QA"}),
        )
        listed = client.get("/api/roles", headers=AUTH)

    assert put.status_code == 200
    assert put.json()["name"] == "qa"
    assert put.json()["capabilities"] == ["tools.read"]
    names = {entry["name"] for entry in listed.json()["roles"]}
    assert {"qa", "admin"} <= names
    assert asyncio.run(store.get("qa")).description == "QA"


def test_role_write_requires_capability(tmp_path):
    client, store, _ = _client(tmp_path, roles=["publisher"])
    with client:
        put = client.put(
            "/api/roles/qa", headers=AUTH, content=json.dumps({"capabilities": ["tools.read"]})
        )
        delete = client.delete("/api/roles/qa", headers=AUTH)

    assert put.status_code == 403
    assert delete.status_code == 403
    assert asyncio.run(store.get("qa")) is None


def test_builtin_role_is_immutable(tmp_path):
    client, store, _ = _client(tmp_path, roles=["admin"])
    with client:
        response = client.delete("/api/roles/admin", headers=AUTH)

    assert response.status_code == 409
    assert response.json() == {"error": "builtin_role_immutable"}
    assert asyncio.run(store.get("admin")) is not None


def test_remove_unknown_role_is_404(tmp_path):
    client, _, _ = _client(tmp_path, roles=["admin"])
    with client:
        response = client.delete("/api/roles/nope", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "role_not_found"}


def test_roles_api_requires_store(tmp_path):
    client, _, _ = _client(tmp_path, roles=["admin"], with_store=False)
    with client:
        listed = client.get("/api/roles", headers=AUTH)

    assert listed.status_code == 404
    assert listed.json() == {"error": "role_store_not_configured"}


def test_admin_binds_user_and_audits(tmp_path):
    client, _, store = _client(tmp_path, roles=["admin"])
    with client:
        put = client.put(
            "/api/users/alice", headers=AUTH, content=json.dumps({"roles": ["operator"]})
        )
        listed = client.get("/api/users", headers=AUTH)

    assert put.status_code == 200
    assert put.json()["subject"] == "alice"
    assert put.json()["roles"] == ["operator"]
    assert [entry["subject"] for entry in listed.json()["users"]] == ["alice"]
    assert asyncio.run(store.get("local", "alice")) is not None


def test_user_bindings_are_tenant_scoped(tmp_path):
    client, _, store = _client(tmp_path, roles=["admin"])
    with client:
        put = client.put(
            "/api/users/alice", headers=AUTH, content=json.dumps({"roles": ["operator"]})
        )
        other = client.get("/api/users?tenant=other", headers=AUTH)
        unbind = client.delete("/api/users/alice", headers=AUTH)

    assert put.status_code == 200
    assert other.json()["users"] == []
    assert unbind.status_code == 200
    assert asyncio.run(store.get("local", "alice")) is None


def test_admin_has_role_management_capabilities():
    assert {"roles.read", "roles.manage"} <= set(CAPABILITIES_ALL)


def test_editing_a_builtin_keeps_it_immutable(tmp_path):
    client, store, _ = _client(tmp_path, roles=["admin"])
    with client:
        put = client.put(
            "/api/roles/operator", headers=AUTH, content=json.dumps({"capabilities": ["chat.run"]})
        )
        delete = client.delete("/api/roles/operator", headers=AUTH)

    assert put.status_code == 200
    assert put.json()["builtin"] is True
    assert set(put.json()["capabilities"]) == {"chat.run"}
    assert delete.status_code == 409
    assert delete.json() == {"error": "builtin_role_immutable"}


def test_seed_backfills_new_capabilities_into_builtin(tmp_path):
    from adk_agent import cli

    store = FileRoleStore(tmp_path / "roles")
    # A store seeded before roles.read/roles.manage existed.
    asyncio.run(
        store.add(RoleDefinition(name="admin", capabilities=("chat.run", "ops.read"), builtin=True))
    )
    asyncio.run(store.add(RoleDefinition(name="qa", capabilities=("tools.read",))))

    cli._seed_role_store(store)

    admin = asyncio.run(store.get("admin"))
    assert admin.builtin is True
    assert {"roles.read", "roles.manage", "chat.run", "ops.read"} <= set(admin.capabilities)
    # Operator-defined roles are left exactly as written.
    assert asyncio.run(store.get("qa")) == RoleDefinition(name="qa", capabilities=("tools.read",))


def test_user_write_requires_capability(tmp_path):
    client, _, store = _client(tmp_path, roles=["operator"])
    with client:
        put = client.put("/api/users/alice", headers=AUTH, content=json.dumps({"roles": ["admin"]}))
        delete = client.delete("/api/users/alice", headers=AUTH)

    assert put.status_code == 403
    assert delete.status_code == 403
    assert asyncio.run(store.list("local")) == []


def test_non_admin_cannot_target_another_tenant(tmp_path):
    client, _, _ = _client(tmp_path, roles=["operator"])
    with client:
        response = client.get("/api/users?tenant=other", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_invalid_tenant_is_rejected(tmp_path):
    client, _, _ = _client(tmp_path, roles=["admin"])
    with client:
        response = client.get("/api/users?tenant=bad/tenant", headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_tenant"}


def test_users_api_requires_store(tmp_path):
    client, _, _ = _client(tmp_path, roles=["admin"], with_bindings=False)
    with client:
        response = client.get("/api/users", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "user_binding_store_not_configured"}
