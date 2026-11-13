"""SLICE-074: HttpEvalReportStore speaks the control-plane eval endpoints."""

from __future__ import annotations

import asyncio

import httpx

from adk_agent.core import AgentManifest, EvalReport
from adk_agent.registry import HttpEvalReportStore, published_from
from adk_agent.registry.service import build_registry_service_app


class MemoryEvalStore:
    def __init__(self) -> None:
        self.reports = {}

    async def put(self, tenant, agent_id, version, report):
        self.reports[(tenant, agent_id, version)] = report
        return report

    async def get(self, tenant, agent_id, version):
        return self.reports.get((tenant, agent_id, version))

    async def has(self, tenant, agent_id, version):
        return (tenant, agent_id, version) in self.reports


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
        return ["t1"]


def _manifest() -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="t1",
        owner="t1",
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _client() -> HttpEvalReportStore:
    registry = MemoryRegistry()
    asyncio.run(registry.publish(published_from(_manifest())))
    app = build_registry_service_app(registry, eval_reports=MemoryEvalStore(), auth_token="secret")
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://registry"
    )
    return HttpEvalReportStore("http://registry", auth_token="secret", client=http_client)


def test_roundtrip_and_missing():
    client = _client()
    report = EvalReport(suite_id="smoke", version="1", passed=1, total=2)

    asyncio.run(client.put("t1", "bot", "1.0.0", report))

    assert asyncio.run(client.get("t1", "bot", "1.0.0")) == report
    assert asyncio.run(client.has("t1", "bot", "1.0.0")) is True
    assert asyncio.run(client.get("t1", "bot", "9.9.9")) is None
    assert asyncio.run(client.has("t1", "bot", "9.9.9")) is False
