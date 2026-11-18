"""SLICE-153: write and base routes check console capabilities."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import AgentManifest
from adk_agent.registry import (
    FileAgentLifecycleStore,
    FileAgentRegistry,
    FileToolGrantStore,
    published_from,
)

AUTH = {"Authorization": "Bearer secret"}


def _manifest(tenant: str = "local") -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant=tenant,
        owner=tenant,
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _record(tmp_path, tenant: str = "local"):
    registry = FileAgentRegistry(tmp_path / "registry")
    record = published_from(_manifest(tenant))
    asyncio.run(registry.publish(record))
    return registry, record


def _app(tmp_path, *, roles=None):
    registry, _record_value = _record(tmp_path)
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        registry=registry,
        lifecycle=FileAgentLifecycleStore(tmp_path / "registry"),
        tool_grants=FileToolGrantStore(tmp_path / "grants"),
    )


def _grant_body(record) -> dict:
    return {
        "tenant": record.manifest.tenant,
        "agent_id": record.manifest.id,
        "version": record.manifest.version,
        "digest": record.digest,
        "tool_id": "crm.read",
        "reason": "temporary access",
    }


def test_load_requires_registry_load(tmp_path):
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        loaded = client.post("/api/registry/load", content=b"not json", headers=AUTH)

    assert loaded.status_code == 403
    assert loaded.json() == {"error": "forbidden"}


def test_unload_requires_registry_load(tmp_path):
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        unloaded = client.post("/api/registry/unload", json={"name": "bot"}, headers=AUTH)

    assert unloaded.status_code == 403
    assert unloaded.json() == {"error": "forbidden"}


def test_tool_grant_request_requires_grants_request(tmp_path):
    _registry, record = _record(tmp_path)
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        requested = client.post("/api/tool-grants", json=_grant_body(record), headers=AUTH)

    assert requested.status_code == 403
    assert requested.json() == {"error": "forbidden"}


def test_publisher_can_request_a_tool_grant(tmp_path):
    _registry, record = _record(tmp_path)
    with TestClient(_app(tmp_path, roles=["publisher"])) as client:
        requested = client.post("/api/tool-grants", json=_grant_body(record), headers=AUTH)

    assert requested.status_code == 201
    assert requested.json()["status"] == "pending"


def test_grant_request_button_is_capability_gated(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        page = client.get("/", headers=AUTH)

    assert page.status_code == 200
    assert 'id="grant-request" data-capability="grants.request"' in page.text
