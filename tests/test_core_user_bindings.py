"""SLICE-259: user binding store ((tenant, subject) -> roles)."""

from __future__ import annotations

import asyncio
import importlib.util
import os

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    UserBinding,
    UserBindingConflict,
)
from adk_agent.registry import FileUserBindingStore, PostgresUserBindingStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _binding(
    tenant: str = "acme", subject: str = "alice", roles: tuple[str, ...] = ("operator",)
) -> UserBinding:
    return UserBinding(tenant=tenant, subject=subject, roles=roles)


def test_user_binding_normalizes_roles():
    binding = _binding(roles=("operator", "admin", "operator"))
    assert binding.roles == ("admin", "operator")


def test_user_binding_rejects_invalid_tenant():
    with pytest.raises(ValidationError):
        _binding(tenant="bad tenant!")


def test_user_binding_rejects_invalid_role():
    with pytest.raises(ValidationError):
        _binding(roles=("has space",))


def test_file_user_binding_store_roundtrip(tmp_path):
    store = FileUserBindingStore(tmp_path)
    acme = _binding(tenant="acme", subject="alice", roles=("operator",))
    other = _binding(tenant="other", subject="alice", roles=("publisher",))

    assert asyncio.run(store.add(acme)) == acme
    assert asyncio.run(store.add(other)) == other
    assert asyncio.run(store.get("acme", "alice")) == acme
    assert asyncio.run(store.get("other", "alice")) == other

    listed = asyncio.run(store.list("acme"))
    assert [(b.tenant, b.subject) for b in listed] == [("acme", "alice")]

    assert asyncio.run(store.delete("acme", "alice")) is True
    assert asyncio.run(store.get("acme", "alice")) is None
    assert asyncio.run(store.delete("acme", "alice")) is False


def test_file_user_binding_store_conflict(tmp_path):
    store = FileUserBindingStore(tmp_path)
    asyncio.run(store.add(_binding(subject="alice", roles=("operator",))))

    with pytest.raises(UserBindingConflict):
        asyncio.run(store.add(_binding(subject="alice", roles=("publisher",))))


def test_file_user_binding_subject_is_path_safe(tmp_path):
    store = FileUserBindingStore(tmp_path)
    hostile = "auth0|abc/../def@example.com"
    binding = _binding(subject=hostile, roles=("base",))

    assert asyncio.run(store.add(binding)) == binding

    # The subject was hashed into a flat 64-hex filename; no path escaped.
    tenant_dir = tmp_path / "acme"
    assert tenant_dir.is_dir()
    files = [path for path in tenant_dir.iterdir() if path.is_file()]
    assert len(files) == 1
    assert files[0].name.endswith(".json")
    assert len(files[0].stem) == 64 and all(c in "0123456789abcdef" for c in files[0].stem)

    assert asyncio.run(store.get("acme", hostile)) == binding
    assert asyncio.run(store.list("acme")) == [binding]
    assert asyncio.run(store.delete("acme", hostile)) is True


@_live
@_needs_driver
def test_postgres_user_binding_store_roundtrip():
    store = PostgresUserBindingStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    subject = f"user{suffix}"
    binding = _binding(tenant=tenant, subject=subject, roles=("operator",))

    async def flow() -> None:
        try:
            assert await store.add(binding) == binding
            assert await store.add(binding) == binding  # idempotent retry
            assert await store.get(tenant, subject) == binding
            assert (tenant, subject) in [(b.tenant, b.subject) for b in await store.list(tenant)]

            assert await store.delete(tenant, subject) is True
            assert await store.get(tenant, subject) is None
            assert await store.delete(tenant, subject) is False
        finally:
            await store.aclose()

    asyncio.run(flow())
