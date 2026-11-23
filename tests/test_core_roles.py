"""SLICE-258: role definition store (role name -> capability set)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    CAPABILITIES_ALL,
    CAPABILITIES_BASE,
    CAPABILITIES_OPERATOR,
    CAPABILITIES_PUBLISHER,
    RoleConflict,
    RoleDefinition,
    seed_builtin_roles,
)
from adk_agent.registry import FileRoleStore, PostgresRoleStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _role(name: str, capabilities: tuple[str, ...]) -> RoleDefinition:
    return RoleDefinition(name=name, capabilities=capabilities)


def test_role_definition_normalizes_capabilities():
    role = _role("dev", ("tools.read", "chat.run", "tools.read"))
    assert role.capabilities == ("chat.run", "tools.read")
    assert role.builtin is False


def test_role_definition_rejects_invalid_name():
    with pytest.raises(ValidationError):
        _role("bad name!", ("chat.run",))


def test_file_role_store_roundtrip(tmp_path):
    store = FileRoleStore(tmp_path)
    role = _role("qa", ("chat.run", "runs.read"))

    assert asyncio.run(store.add(role)) == role
    assert asyncio.run(store.get("qa")) == role
    assert [r.name for r in asyncio.run(store.list())] == ["qa"]

    assert asyncio.run(store.delete("qa")) is True
    assert asyncio.run(store.get("qa")) is None
    assert asyncio.run(store.list()) == []


def test_file_role_store_conflict(tmp_path):
    store = FileRoleStore(tmp_path)
    asyncio.run(store.add(_role("qa", ("chat.run",))))

    with pytest.raises(RoleConflict):
        asyncio.run(store.add(_role("qa", ("runs.read",))))


def test_seed_builtin_roles_match_capabilities():
    roles = {role.name: role for role in seed_builtin_roles()}

    assert set(roles) == {"admin", "operator", "ops", "approver", "publisher", "developer", "base"}
    assert set(roles["admin"].capabilities) == set(CAPABILITIES_ALL)
    assert set(roles["base"].capabilities) == set(CAPABILITIES_BASE)
    assert set(roles["operator"].capabilities) == set(CAPABILITIES_OPERATOR)
    assert set(roles["ops"].capabilities) == set(CAPABILITIES_OPERATOR)
    assert set(roles["approver"].capabilities) == set(CAPABILITIES_OPERATOR)
    assert set(roles["publisher"].capabilities) == set(CAPABILITIES_PUBLISHER)
    assert set(roles["developer"].capabilities) == set(CAPABILITIES_PUBLISHER)
    assert all(role.builtin for role in roles.values())


def test_capabilities_moved_out_of_console():
    console = (Path(__file__).resolve().parents[1] / "src" / "adk_agent" / "console.py").read_text(
        encoding="utf-8"
    )

    assert "_CAPABILITIES_ALL =" not in console
    assert "CAPABILITIES_ALL" in console


@_live
@_needs_driver
def test_postgres_role_store_roundtrip():
    store = PostgresRoleStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    name = f"qa{suffix}"
    role = _role(name, ("chat.run", "runs.read"))

    async def flow() -> None:
        try:
            assert await store.add(role) == role
            assert await store.add(role) == role  # idempotent retry
            assert await store.get(name) == role
            assert name in [entry.name for entry in await store.list()]

            assert await store.delete(name) is True
            assert await store.get(name) is None
            assert await store.delete(name) is False
        finally:
            await store.aclose()

    asyncio.run(flow())
