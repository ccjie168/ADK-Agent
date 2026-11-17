"""SLICE-071: HttpAgentRegistry speaks the control-plane contract."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adk_agent.core import AgentManifest, AgentRef
from adk_agent.registry import (
    HttpAgentRegistry,
    RegistryConflict,
    RegistryForbidden,
    RegistryServiceUnavailable,
    published_from,
)
from adk_agent.registry.service import build_registry_service_app


class MemoryRegistry:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], object] = {}

    async def publish(self, agent):
        key = (agent.manifest.tenant, agent.manifest.id, agent.manifest.version)
        existing = self.records.get(key)
        if existing is not None:
            if existing.digest != agent.digest:
                raise RegistryConflict("digest mismatch")
            return existing
        self.records[key] = agent
        return agent

    async def get(self, ref, tenant):
        return self.records.get((tenant, ref.id, ref.version))

    async def list(self, tenant):
        return sorted(
            (record for key, record in self.records.items() if key[0] == tenant),
            key=lambda record: (record.manifest.id, record.manifest.version),
        )

    async def tenants(self):
        return sorted({key[0] for key in self.records})


def _manifest(tenant: str = "t1", version: str = "1.0.0", description: str = "bot"):
    return AgentManifest(
        id="bot",
        version=version,
        tenant=tenant,
        owner=tenant,
        description=description,
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="in_process",
    )


def _client(auth_token: str = "secret") -> HttpAgentRegistry:
    app = build_registry_service_app(MemoryRegistry(), auth_token="secret")
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://registry"
    )
    return HttpAgentRegistry("http://registry", auth_token=auth_token, client=http_client)


def test_roundtrip_and_missing():
    client = _client()
    record = published_from(_manifest())

    asyncio.run(client.publish(record))

    ref = AgentRef(id=record.manifest.id, version=record.manifest.version, digest=record.digest)
    missing = AgentRef(id="bot", version="9.9.9", digest=record.digest)

    assert asyncio.run(client.list("t1")) == [record]
    assert asyncio.run(client.tenants()) == ["t1"]
    assert asyncio.run(client.get(ref, "t1")) == record
    assert asyncio.run(client.get(missing, "t1")) is None


def test_conflict_and_forbidden_mapping():
    client = _client()
    asyncio.run(client.publish(published_from(_manifest())))

    with pytest.raises(RegistryConflict):
        asyncio.run(client.publish(published_from(_manifest(description="other"))))

    with pytest.raises(RegistryForbidden):
        asyncio.run(_client("wrong").publish(published_from(_manifest(version="2.0.0"))))


def test_transport_failure_maps_to_unavailable():
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "registry_unavailable"})

    down = HttpAgentRegistry(
        "http://registry",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fail), base_url="http://registry"),
    )
    broken = HttpAgentRegistry(
        "http://registry",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(server_error), base_url="http://registry"
        ),
    )

    with pytest.raises(RegistryServiceUnavailable):
        asyncio.run(down.tenants())
    with pytest.raises(RegistryServiceUnavailable):
        asyncio.run(broken.tenants())
