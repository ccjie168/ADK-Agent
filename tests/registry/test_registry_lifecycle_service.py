"""SLICE-076: the control plane reads and writes lifecycle state."""

from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

from adk_agent.audit import ListAuditSink
from adk_agent.core import (
    AgentLifecycle,
    AgentManifest,
    Principal,
    transition_lifecycle,
)
from adk_agent.registry import HttpAgentRegistry, published_from
from adk_agent.registry.service import build_registry_service_app

AUTH = {"Authorization": "Bearer secret"}
TOKEN = "alice-token"
OIDC_AUTH = {"Authorization": f"Bearer {TOKEN}"}


class MemoryRegistry:
    def __init__(self) -> None:
        self.records = {}

    async def publish(self, agent):
        self.records[(agent.manifest.tenant, agent.manifest.id, agent.manifest.version)] = agent
        return agent

    async def get(self, ref, tenant):
        return self.records.get((tenant, ref.id, ref.version))

    async def list(self, tenant):
        return [record for key, record in self.records.items() if key[0] == tenant]

    async def tenants(self):
        return sorted({key[0] for key in self.records})


class MemoryLifecycleStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], AgentLifecycle] = {}

    async def get(self, tenant, agent_id, version):
        return self.records.get((tenant, agent_id, version), AgentLifecycle.default())

    async def set(self, tenant, agent_id, version, *, status, changed_by, reason):
        current = await self.get(tenant, agent_id, version)
        record = transition_lifecycle(current, status, changed_by=changed_by, reason=reason)
        self.records[(tenant, agent_id, version)] = record
        return record


class FakeProvider:
    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self._principal


def _manifest(tenant: str = "acme", version: str = "1.0.0") -> AgentManifest:
    return AgentManifest(
        id="bot",
        version=version,
        tenant=tenant,
        owner=tenant,
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


async def _publish(registry, manifest=None):
    await registry.publish(published_from(manifest or _manifest()))


def _path(tenant="acme", version="1.0.0") -> str:
    return f"/v1/agents/{tenant}/bot/{version}/lifecycle"


def _app(registry=None, *, lifecycle=None, oidc=None, audit=None):
    return build_registry_service_app(
        registry if registry is not None else MemoryRegistry(),
        lifecycle=lifecycle if lifecycle is not None else MemoryLifecycleStore(),
        audit=audit,
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
    )


def _put(client, body, headers=AUTH):
    return client.put(_path(), json=body, headers=headers)


def test_default_published():
    with TestClient(_app()) as client:
        response = client.get(_path(), headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "status": "published",
        "changed_at": None,
        "changed_by": None,
        "reason": "",
    }


def test_set_and_get():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry))
    with TestClient(_app(registry)) as client:
        put = _put(client, {"status": "deprecated", "reason": "old"})
        get = client.get(_path(), headers=AUTH)

    assert put.status_code == 200
    assert put.json()["status"] == "deprecated"
    assert get.json()["reason"] == "old"


def test_non_admin_forbidden():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry))
    provider = FakeProvider(Principal(tenant="acme", subject="alice", kind="human"))
    with TestClient(_app(registry, oidc=provider)) as client:
        response = _put(client, {"status": "retired", "reason": "stop"}, headers=OIDC_AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_version_required():
    with TestClient(_app()) as client:
        response = _put(client, {"status": "deprecated", "reason": "old"})

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_invalid_transition():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry))
    with TestClient(_app(registry)) as client:
        assert _put(client, {"status": "retired", "reason": "stop"}).status_code == 200
        response = _put(client, {"status": "published", "reason": "back"})

    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}


def test_invalid_status():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry))
    with TestClient(_app(registry)) as client:
        response = _put(client, {"status": "deleted", "reason": "no"})

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_status"}


def test_audit_records_change():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry))
    sink = ListAuditSink()
    with TestClient(_app(registry, audit=sink)) as client:
        _put(client, {"status": "deprecated", "reason": "old"})

    [event] = [item for item in sink.recent() if item.action == "agent.lifecycle"]
    assert event.status == "ok"
    assert event.target == "acme/bot@1.0.0"
    assert event.tenant == "acme"


def test_client_roundtrip():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry))
    app = _app(registry)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://registry"
    )
    client = HttpAgentRegistry("http://registry", auth_token="secret", client=http_client)

    default = asyncio.run(client.get_lifecycle("acme", "bot", "1.0.0"))
    changed = asyncio.run(client.set_lifecycle("acme", "bot", "1.0.0", "deprecated", reason="old"))

    assert default.status == "published"
    assert changed.status == "deprecated"
    assert asyncio.run(client.get_lifecycle("acme", "bot", "1.0.0")) == changed
