"""SLICE-260: capability resolution from the role definition store."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import (
    CAPABILITIES_ALL,
    CAPABILITIES_BASE,
    CAPABILITIES_OPERATOR,
    RoleDefinition,
    RoleStoreError,
    seed_builtin_roles,
)
from adk_agent.registry import FileRoleStore

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


def _capabilities(roles: list[str], role_store=None) -> set[str]:
    app = build_console_app(_agents(), auth_token="secret", roles=roles, role_store=role_store)
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    return set(response.json()["capabilities"])


def test_capabilities_unchanged_without_store():
    assert _capabilities(["admin"]) == set(CAPABILITIES_ALL)
    assert _capabilities(["operator"]) == set(CAPABILITIES_OPERATOR)
    assert _capabilities(["viewer"]) == BASE


def test_role_store_definitions_grant_capabilities(tmp_path):
    store = FileRoleStore(tmp_path)
    asyncio.run(store.add(RoleDefinition(name="qa", capabilities=("tools.read",))))
    asyncio.run(store.add(RoleDefinition(name="reader", capabilities=("chat.run", "runs.read"))))

    # A role definition is the role's complete capability set.
    assert _capabilities(["qa"], role_store=store) == {"tools.read"}
    assert _capabilities(["qa", "reader"], role_store=store) == {
        "chat.run",
        "runs.read",
        "tools.read",
    }


def test_undefined_role_falls_back_to_base(tmp_path):
    store = FileRoleStore(tmp_path)
    asyncio.run(store.add(RoleDefinition(name="qa", capabilities=("tools.read",))))

    # `admin` is not in the store, so it grants nothing beyond the base floor.
    assert _capabilities(["admin"], role_store=store) == BASE


def test_role_store_failure_fails_closed():
    class BrokenStore:
        async def add(self, role):  # pragma: no cover - unused
            raise AssertionError("not used")

        async def get(self, name):
            raise RoleStoreError("store unavailable")

        async def list(self):  # pragma: no cover - unused
            raise RoleStoreError("store unavailable")

        async def delete(self, name):  # pragma: no cover - unused
            raise AssertionError("not used")

    assert _capabilities(["admin"], role_store=BrokenStore()) == BASE


def test_unrepresentable_role_name_does_not_error(tmp_path):
    store = FileRoleStore(tmp_path)
    asyncio.run(store.add(RoleDefinition(name="qa", capabilities=("tools.read",))))

    # A claim role name the store whitelist rejects must not 500 the request.
    assert _capabilities(["bad name!"], role_store=store) == BASE


def test_seed_builtin_roles_keeps_admin_working(tmp_path):
    store = FileRoleStore(tmp_path)
    for role in seed_builtin_roles():
        asyncio.run(store.add(role))

    assert _capabilities(["admin"], role_store=store) == set(CAPABILITIES_ALL)
    assert _capabilities(["operator"], role_store=store) == set(CAPABILITIES_OPERATOR)


def test_seed_keeps_an_operator_customized_builtin(tmp_path):
    from adk_agent import cli

    store = FileRoleStore(tmp_path)
    asyncio.run(store.add(RoleDefinition(name="admin", capabilities=("tools.read",))))

    cli._seed_role_store(store)

    assert asyncio.run(store.get("admin")) == RoleDefinition(
        name="admin", capabilities=("tools.read",)
    )


def test_console_rejects_two_role_stores(tmp_path, monkeypatch):
    from adk_agent import cli

    monkeypatch.delenv("ROLE_DATABASE_URL", raising=False)
    args = type(
        "Args",
        (),
        {"role_store_dir": str(tmp_path), "role_store_db": "postgresql://x/y"},
    )()
    with pytest.raises(SystemExit) as excinfo:
        cli._role_store(args)
    assert excinfo.value.code == 2
