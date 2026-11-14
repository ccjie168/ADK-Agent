"""SLICE-087: HttpConnectorStore speaks the connector control-plane contract."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adk_agent.core import (
    ConnectorConflict,
    ConnectorForbidden,
    ConnectorNotFound,
    ConnectorSpec,
    ConnectorStoreUnavailable,
    Principal,
)
from adk_agent.registry import FileConnectorStore, HttpConnectorStore
from adk_agent.registry.service import build_registry_service_app

AUTH = {"Authorization": "Bearer secret"}


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


def _spec(**overrides) -> ConnectorSpec:
    data = {
        "connector_id": "crm",
        "tenant": "acme",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
    }
    data.update(overrides)
    return ConnectorSpec(**data)


def _client(tmp_path, *, oidc=None, token="secret", connectors=True):
    app = build_registry_service_app(
        MemoryRegistry(),
        connectors=FileConnectorStore(tmp_path / "connectors") if connectors else None,
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
    )
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://registry"
    )
    return HttpConnectorStore("http://registry", auth_token=token, client=http_client)


def test_roundtrip(tmp_path):
    client = _client(tmp_path)
    spec = _spec()

    async def run():
        try:
            assert await client.add(spec) == spec
            assert await client.list("acme") == [spec]
            assert await client.get("crm") == spec
            disabled = await client.disable("crm", by="cli")
            assert disabled.enabled is False
            assert (await client.disable("crm", by="cli")).enabled is False
        finally:
            await client.aclose()

    asyncio.run(run())


def test_conflict(tmp_path):
    client = _client(tmp_path)

    async def run():
        try:
            await client.add(_spec())
            with pytest.raises(ConnectorConflict):
                await client.add(_spec(base_url="https://other.example.com"))
        finally:
            await client.aclose()

    asyncio.run(run())


def test_missing_and_forbidden(tmp_path):
    client = _client(tmp_path)

    async def run():
        try:
            assert await client.get("missing") is None
            with pytest.raises(ConnectorNotFound):
                await client.disable("missing", by="cli")
        finally:
            await client.aclose()

    asyncio.run(run())

    provider = FakeProvider(Principal(tenant="acme", subject="alice", kind="human"))
    forbidden = _client(tmp_path, oidc=provider, token="token")
    asyncio.run(_expect(forbidden.add(_spec()), ConnectorForbidden, forbidden))


def test_store_unavailable(tmp_path):
    client = _client(tmp_path, connectors=False)

    async def run():
        try:
            with pytest.raises(ConnectorStoreUnavailable):
                await client.list("acme")
        finally:
            await client.aclose()

    asyncio.run(run())


async def _expect(awaitable, error, client):
    try:
        with pytest.raises(error):
            await awaitable
    finally:
        await client.aclose()
