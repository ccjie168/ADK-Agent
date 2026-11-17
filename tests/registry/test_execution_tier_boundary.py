"""SLICE-128: publish and load refuse sandboxed records without a backend."""

from __future__ import annotations

import asyncio
import builtins

import pytest
from fastapi.testclient import TestClient

from adk_agent.core import AgentArtifact, AgentManifest, AgentRef, PublishedAgent
from adk_agent.registry import published_from
from adk_agent.registry.loader import load_agent
from adk_agent.registry.service import build_registry_service_app
from adk_agent.sandbox.agent import (
    AgentSandboxUnavailable,
    SandboxResult,
    agent_sandbox_available,
    set_agent_sandbox_backend,
)


class _Backend:
    async def run(self, artifact, data, input_text):
        return SandboxResult(text="stub")


AUTH = {"Authorization": "Bearer secret"}


class MemoryRegistry:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], PublishedAgent] = {}

    async def publish(self, agent: PublishedAgent) -> PublishedAgent:
        key = (agent.manifest.tenant, agent.manifest.id, agent.manifest.version)
        self.records[key] = agent
        return agent

    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None:
        return self.records.get((tenant, ref.id, ref.version))

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]:
        return [record for key, record in self.records.items() if key[0] == tenant]

    async def tenants(self) -> builtins.list[str]:
        return sorted({key[0] for key in self.records})


def _manifest(tier: str | None = None) -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier=tier,
    )


def _record(tier: str | None = None) -> PublishedAgent:
    return published_from(_manifest(tier))


def _post(client: TestClient, record: PublishedAgent):
    return client.post("/v1/agents", json=record.model_dump(mode="json"), headers=AUTH)


@pytest.fixture(autouse=True)
def _no_backend():
    set_agent_sandbox_backend(None)
    yield
    set_agent_sandbox_backend(None)


def test_publish_requires_a_declared_tier():
    with TestClient(build_registry_service_app(MemoryRegistry(), auth_token="secret")) as client:
        response = _post(client, _record())

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_record"}


def test_sandboxed_publish_needs_a_backend():
    with TestClient(build_registry_service_app(MemoryRegistry(), auth_token="secret")) as client:
        response = _post(client, _record("sandboxed"))

    assert response.status_code == 409
    assert response.json() == {"error": "sandbox_unavailable"}


def test_sandboxed_publish_with_backend():
    set_agent_sandbox_backend(_Backend())
    with TestClient(build_registry_service_app(MemoryRegistry(), auth_token="secret")) as client:
        response = _post(client, _record("sandboxed"))

    assert response.status_code == 201
    assert response.json()["manifest"]["execution_tier"] == "sandboxed"


def test_in_process_publish_is_accepted():
    with TestClient(build_registry_service_app(MemoryRegistry(), auth_token="secret")) as client:
        response = _post(client, _record("in_process"))

    assert response.status_code == 201


class _Registry:
    def __init__(self, record: PublishedAgent) -> None:
        self.record = record

    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None:
        return self.record


class _Trust:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, artifact: AgentArtifact) -> None:
        self.calls += 1


class _Loader:
    def __init__(self) -> None:
        self.calls = 0

    async def load(self, artifact: AgentArtifact, store) -> object:
        self.calls += 1
        return object()


class _Store:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, digest: str) -> bytes:
        self.calls += 1
        return b"zip!"


def _load(record: PublishedAgent, trust: _Trust, loader: _Loader) -> object:
    ref = AgentRef(id="bot", version="1.0.0", digest=record.digest)
    return asyncio.run(
        load_agent(
            registry=_Registry(record),
            ref=ref,
            tenant="acme",
            store=_Store(),
            loader=loader,
            trust=trust,
        )
    )


def _with_artifact(tier: str | None) -> PublishedAgent:
    artifact = AgentArtifact(digest="sha256:" + "a" * 64, size=1)
    return published_from(_manifest(tier), artifact=artifact)


def test_load_agent_gates_sandboxed_records():
    record = _with_artifact("sandboxed")
    trust, loader = _Trust(), _Loader()

    with pytest.raises(AgentSandboxUnavailable):
        _load(record, trust, loader)
    assert trust.calls == 0
    assert loader.calls == 0

    set_agent_sandbox_backend(_Backend())
    loaded = _load(record, trust, loader)
    assert type(loaded).__name__ == "SandboxAgent"
    assert trust.calls == 1
    assert loader.calls == 0


def test_a_placeholder_backend_does_not_count():
    with pytest.raises(TypeError):
        set_agent_sandbox_backend(object())

    assert agent_sandbox_available() is False


def test_load_agent_allows_legacy_and_in_process_records():
    for tier in (None, "in_process"):
        trust, loader = _Trust(), _Loader()
        assert _load(_with_artifact(tier), trust, loader) is not None
        assert trust.calls == 1
        assert loader.calls == 1
