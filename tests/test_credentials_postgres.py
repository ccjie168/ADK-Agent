"""SLICE-121: the Postgres credential store (live case needs TEST_POSTGRES_URL)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone

import pytest

from adk_agent.core import CredentialBinding, CredentialNotFound
from adk_agent.registry import PostgresCredentialStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _binding(ref: str = "secret://acme/token", **overrides) -> CredentialBinding:
    data = {
        "credential_id": "crm",
        "tenant": "acme",
        "description": "CRM token",
        "created_by": "admin",
        "created_at": datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    }
    data["secret_ref"] = ref
    data.update(overrides)
    return CredentialBinding(**data)


@_live
@_needs_driver
def test_postgres_roundtrip_and_isolation():
    store = PostgresCredentialStore(_LIVE_URL)
    suffix = os.urandom(4).hex()
    tenant = f"acme{suffix}"
    other = f"other{suffix}"
    credential_id = f"cred{suffix}"
    acme = _binding(
        credential_id=credential_id,
        tenant=tenant,
        ref=f"secret://{tenant}/token",
    )
    foreign = _binding(
        credential_id=credential_id,
        tenant=other,
        ref=f"secret://{other}/token",
    )

    async def flow() -> None:
        try:
            assert await store.add(acme) == acme
            assert await store.add(acme) == acme
            assert await store.get(tenant, credential_id) == acme
            assert await store.get(other, credential_id) is None

            assert await store.add(foreign) == foreign
            listed = await store.list(tenant)
            assert [binding.tenant for binding in listed] == [tenant]
            assert await store.get(other, credential_id) == foreign

            disabled = await store.disable(tenant, credential_id, by="alice")
            again = await store.disable(tenant, credential_id, by="bob")
            assert disabled.enabled is False
            assert again.enabled is False
            assert (await store.get(tenant, credential_id)).enabled is False

            with pytest.raises(CredentialNotFound):
                await store.disable(tenant, "missing", by="alice")
        finally:
            await store.aclose()

    asyncio.run(flow())
