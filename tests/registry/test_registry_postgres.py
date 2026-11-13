"""SLICE-070: the Postgres registry pins versions with the file registry semantics.

Set TEST_POSTGRES_URL to run the live cases against a real database.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import uuid

import pytest

from adk_agent.core import AgentManifest, AgentRef
from adk_agent.registry import (
    PostgresAgentRegistry,
    RegistryConflict,
    RegistryIntegrityError,
    RegistryStoreUnavailable,
    published_from,
)

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _manifest(tenant: str, version: str = "1.0.0", description: str = "support"):
    return AgentManifest(
        id="bot",
        version=version,
        tenant=tenant,
        owner=tenant,
        description=description,
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _tenant() -> str:
    return "t" + uuid.uuid4().hex[:12]


def _ref(manifest: AgentManifest, digest: str) -> AgentRef:
    return AgentRef(id=manifest.id, version=manifest.version, digest=digest)


def _registry() -> PostgresAgentRegistry:
    return PostgresAgentRegistry(_LIVE_URL)


def _rewrite_record(tenant: str, version: str, record: dict) -> None:
    asyncpg = importlib.import_module("asyncpg")

    async def run() -> None:
        conn = await asyncpg.connect(_LIVE_URL.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            await conn.execute(
                "UPDATE adk_agent_versions SET record = $1::jsonb "
                "WHERE tenant = $2 AND agent_id = 'bot' AND version = $3",
                json.dumps(record),
                tenant,
                version,
            )
        finally:
            await conn.close()

    asyncio.run(run())


def test_unsupported_url_rejected():
    with pytest.raises(RegistryStoreUnavailable):
        PostgresAgentRegistry("mysql://localhost/adk")


@_live
@_needs_driver
def test_live_publish_then_get():
    registry = _registry()
    tenant = _tenant()
    published = published_from(_manifest(tenant))

    stored = asyncio.run(registry.publish(published))

    assert stored.digest == published.digest
    assert (
        asyncio.run(registry.get(_ref(published.manifest, published.digest), tenant)) == published
    )


@_live
@_needs_driver
def test_live_publish_is_idempotent():
    registry = _registry()
    tenant = _tenant()
    published = published_from(_manifest(tenant))

    first = asyncio.run(registry.publish(published))
    second = asyncio.run(registry.publish(published))

    assert first == second == published


@_live
@_needs_driver
def test_live_conflict_on_different_digest():
    registry = _registry()
    tenant = _tenant()
    asyncio.run(registry.publish(published_from(_manifest(tenant))))

    with pytest.raises(RegistryConflict):
        asyncio.run(registry.publish(published_from(_manifest(tenant, description="other"))))


@_live
@_needs_driver
def test_live_list_and_tenants():
    registry = _registry()
    tenant = _tenant()
    other = _tenant()
    asyncio.run(registry.publish(published_from(_manifest(tenant, version="1.1.0"))))
    asyncio.run(registry.publish(published_from(_manifest(tenant, version="1.0.0"))))
    asyncio.run(registry.publish(published_from(_manifest(other))))

    listed = asyncio.run(registry.list(tenant))
    tenants = asyncio.run(registry.tenants())

    assert [record.manifest.version for record in listed] == ["1.0.0", "1.1.0"]
    assert tenant in tenants and other in tenants


@_live
@_needs_driver
def test_live_get_miss_returns_none():
    registry = _registry()
    tenant = _tenant()
    published = published_from(_manifest(tenant))
    asyncio.run(registry.publish(published))

    missing = AgentRef(id="bot", version="1.0.0", digest="sha256:" + "0" * 64)

    assert asyncio.run(registry.get(missing, tenant)) is None


@_live
@_needs_driver
def test_live_tampered_record_raises():
    registry = _registry()
    tenant = _tenant()
    published = published_from(_manifest(tenant))
    asyncio.run(registry.publish(published))
    tampered = published.model_dump(mode="json")
    tampered["manifest"]["description"] = "tampered"
    _rewrite_record(tenant, published.manifest.version, tampered)

    with pytest.raises(RegistryIntegrityError):
        asyncio.run(registry.list(tenant))


@_live
@_needs_driver
def test_live_unreachable_database():
    registry = PostgresAgentRegistry("postgresql://adk:adk@127.0.0.1:1/adk")

    with pytest.raises(RegistryStoreUnavailable):
        asyncio.run(registry.list(_tenant()))
