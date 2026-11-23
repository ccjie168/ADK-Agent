"""SLICE-262: user binding roles feed console capability resolution."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import (
    CAPABILITIES_BASE,
    CAPABILITIES_OPERATOR,
    UserBinding,
    UserBindingStoreError,
    seed_builtin_roles,
)
from adk_agent.registry import FileRoleStore, FileUserBindingStore

AUTH = {"Authorization": "Bearer secret"}
BASE = set(CAPABILITIES_BASE)


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _stores(tmp_path):
    role_store = FileRoleStore(tmp_path / "roles")
    for role in seed_builtin_roles():
        asyncio.run(role_store.add(role))
    return role_store, FileUserBindingStore(tmp_path / "users")


def _capabilities(tmp_path, *, roles, subject="console_user", tenant="local", bindings=None):
    role_store, binding_store = _stores(tmp_path)
    for binding in bindings or ():
        asyncio.run(binding_store.add(binding))
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=roles,
        role_store=role_store,
        user_binding_store=binding_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["subject"] == subject
    return set(response.json()["capabilities"])


def test_capabilities_unchanged_without_binding_store(tmp_path):
    role_store = FileRoleStore(tmp_path / "roles")
    for role in seed_builtin_roles():
        asyncio.run(role_store.add(role))
    app = build_console_app(
        _agents(), auth_token="secret", roles=["operator"], role_store=role_store
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers=AUTH)

    assert set(response.json()["capabilities"]) == set(CAPABILITIES_OPERATOR)


def test_binding_roles_join_token_roles(tmp_path):
    capabilities = _capabilities(
        tmp_path,
        roles=["base"],
        bindings=[UserBinding(tenant="local", subject="console_user", roles=("operator",))],
    )

    assert capabilities == set(CAPABILITIES_OPERATOR)


def test_union_never_drops_token_capabilities(tmp_path):
    # Token says publisher, the binding says base: resolution is a union, so
    # capabilities never fall below what the token grants.
    capabilities = _capabilities(
        tmp_path,
        roles=["publisher"],
        bindings=[UserBinding(tenant="local", subject="console_user", roles=("base",))],
    )

    assert "registry.publish" in capabilities
    assert capabilities >= BASE


def test_binding_with_undefined_role_adds_nothing(tmp_path):
    capabilities = _capabilities(
        tmp_path,
        roles=["base"],
        bindings=[UserBinding(tenant="local", subject="console_user", roles=("ghost",))],
    )

    assert capabilities == BASE


def test_binding_is_tenant_scoped(tmp_path):
    capabilities = _capabilities(
        tmp_path,
        roles=["base"],
        bindings=[UserBinding(tenant="other", subject="console_user", roles=("admin",))],
    )

    assert capabilities == BASE
    assert "roles.manage" not in capabilities


def test_binding_failure_keeps_token_roles(tmp_path):
    class BrokenBindings:
        async def add(self, binding):  # pragma: no cover - unused
            raise AssertionError("not used")

        async def get(self, tenant, subject):
            raise UserBindingStoreError("store unavailable")

        async def list(self, tenant):  # pragma: no cover - unused
            raise UserBindingStoreError("store unavailable")

        async def delete(self, tenant, subject):  # pragma: no cover - unused
            raise AssertionError("not used")

    role_store, _ = _stores(tmp_path)
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=["operator"],
        role_store=role_store,
        user_binding_store=BrokenBindings(),
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers=AUTH)

    assert set(response.json()["capabilities"]) == set(CAPABILITIES_OPERATOR)


def test_bound_user_gains_panel_access(tmp_path):
    role_store, binding_store = _stores(tmp_path)
    asyncio.run(
        binding_store.add(UserBinding(tenant="local", subject="console_user", roles=("operator",)))
    )
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=["base"],
        role_store=role_store,
        user_binding_store=binding_store,
    )
    with TestClient(app) as client:
        allowed = client.get("/api/audit?limit=5", headers=AUTH)

    assert allowed.status_code == 200
