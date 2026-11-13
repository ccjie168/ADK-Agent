"""SLICE-074: the registry service stores eval reports for published versions."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from adk_agent.core import AgentManifest, EvalReport, Principal
from adk_agent.registry import EvalReportConflict, published_from
from adk_agent.registry.service import build_registry_service_app

AUTH = {"Authorization": "Bearer secret"}
TOKEN = "alice-token"
OIDC_AUTH = {"Authorization": f"Bearer {TOKEN}"}


class MemoryRegistry:
    def __init__(self) -> None:
        self.records = {}

    async def publish(self, agent):
        key = (agent.manifest.tenant, agent.manifest.id, agent.manifest.version)
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


class MemoryEvalStore:
    def __init__(self) -> None:
        self.reports: dict[tuple[str, str, str], EvalReport] = {}

    async def put(self, tenant, agent_id, version, report):
        key = (tenant, agent_id, version)
        existing = self.reports.get(key)
        if existing is not None and existing.model_dump(mode="json") != report.model_dump(
            mode="json"
        ):
            raise EvalReportConflict("different report")
        self.reports[key] = report
        return existing or report

    async def get(self, tenant, agent_id, version):
        return self.reports.get((tenant, agent_id, version))

    async def has(self, tenant, agent_id, version):
        return (tenant, agent_id, version) in self.reports


class FakeProvider:
    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self._principal


def _manifest(tenant: str = "t1", version: str = "1.0.0"):
    return AgentManifest(
        id="bot",
        version=version,
        tenant=tenant,
        owner=tenant,
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _report(passed: int = 1, total: int = 2) -> EvalReport:
    return EvalReport(suite_id="smoke", version="1", passed=passed, total=total)


def _app(registry, *, eval_reports=None, oidc=None):
    return build_registry_service_app(
        registry,
        eval_reports=eval_reports if eval_reports is not None else MemoryEvalStore(),
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
    )


async def _publish(registry, manifest):
    await registry.publish(published_from(manifest))


def _path(tenant="t1", agent_id="bot", version="1.0.0") -> str:
    return f"/v1/agents/{tenant}/{agent_id}/{version}/eval"


def test_put_then_get():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry, _manifest()))
    with TestClient(_app(registry)) as client:
        put = client.put(_path(), json=_report().model_dump(mode="json"), headers=AUTH)
        get = client.get(_path(), headers=AUTH)

    assert put.status_code == 201
    assert get.status_code == 200
    assert get.json() == _report().model_dump(mode="json")


def test_version_required():
    with TestClient(_app(MemoryRegistry())) as client:
        response = client.put(_path(), json=_report().model_dump(mode="json"), headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_missing_report():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry, _manifest()))
    with TestClient(_app(registry)) as client:
        response = client.get(_path(), headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "eval_report_not_found"}


def test_conflict():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry, _manifest()))
    with TestClient(_app(registry)) as client:
        assert (
            client.put(_path(), json=_report().model_dump(mode="json"), headers=AUTH).status_code
            == 201
        )
        response = client.put(
            _path(), json=_report(passed=2, total=2).model_dump(mode="json"), headers=AUTH
        )

    assert response.status_code == 409
    assert response.json() == {"error": "eval_report_conflict"}


def test_cross_tenant_forbidden():
    provider = FakeProvider(Principal(tenant="t1", subject="alice", kind="human"))
    registry = MemoryRegistry()
    asyncio.run(_publish(registry, _manifest(tenant="t2")))
    with TestClient(_app(registry, oidc=provider)) as client:
        response = client.put(
            _path(tenant="t2"), json=_report().model_dump(mode="json"), headers=OIDC_AUTH
        )

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


def test_invalid_report():
    registry = MemoryRegistry()
    asyncio.run(_publish(registry, _manifest()))
    with TestClient(_app(registry)) as client:
        response = client.put(_path(), json={"suite_id": ""}, headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_report"}
