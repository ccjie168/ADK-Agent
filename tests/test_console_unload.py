"""SLICE-083: on-demand agents can be unloaded and swapped."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentArtifact, AgentManifest, Principal
from adk_agent.registry import (
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    TrustStore,
    artifact_digest,
    pack_agent,
    published_from,
    sign_digest,
)

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")

AUTH = {"Authorization": "Bearer secret"}


def _key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _raw(key) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _manifest(version="1.0.0", tenant="acme") -> AgentManifest:
    return AgentManifest(
        id="bot",
        version=version,
        tenant=tenant,
        owner=tenant,
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _publish(tmp_path, key, version="1.0.0"):
    project = tmp_path / f"project-{version}"
    project.mkdir()
    (project / "manifest.json").write_text(_manifest(version).model_dump_json(), encoding="utf-8")
    (project / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        "agent = LlmAgent(name='bot', model='gemini-2.5-pro', instruction='x')\n",
        encoding="utf-8",
    )
    data = pack_agent(project)
    digest = artifact_digest(data)
    artifact = AgentArtifact(
        digest=digest, size=len(data), signature=sign_digest(digest, key), key_id="k1"
    )
    asyncio.run(FileArtifactStore(tmp_path / "store").put(artifact, data))
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published_from(_manifest(version), artifact=artifact)))
    return registry


def _app(tmp_path, key, *, agents=None, audit=None, oidc=None):
    return build_console_app(
        agents or {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
        registry=FileAgentRegistry(tmp_path / "registry"),
        artifact_store=FileArtifactStore(tmp_path / "store"),
        artifact_loader=InProcessArtifactLoader(),
        artifact_trust=TrustStore({"k1": _raw(key)}),
        audit_sink=audit,
    )


def _load(client, version="1.0.0", headers=AUTH):
    return client.post(
        "/api/registry/load",
        json={"tenant": "acme", "id": "bot", "version": version},
        headers=headers,
    )


def _unload(client, headers=AUTH):
    return client.post("/api/registry/unload", json={"name": "bot"}, headers=headers)


@needs_crypto
def test_unload_on_demand(tmp_path):
    key = _key()
    _publish(tmp_path, key)
    with TestClient(_app(tmp_path, key)) as client:
        assert _load(client).status_code == 200
        response = _unload(client)
        agents = client.get("/api/agents", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"name": "bot", "unloaded": True}
    assert [item["name"] for item in agents.json()] == ["probe"]


@needs_crypto
def test_startup_agent_not_unloadable(tmp_path):
    key = _key()
    startup = LlmAgent(name="bot", model="gemini-2.5-pro", instruction="x")
    with TestClient(_app(tmp_path, key, agents={"bot": startup})) as client:
        response = _unload(client)

    assert response.status_code == 409
    assert response.json() == {"error": "not_unloadable"}


@needs_crypto
def test_unknown_agent(tmp_path):
    with TestClient(_app(tmp_path, _key())) as client:
        response = _unload(client)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


@needs_crypto
def test_audit_records_unload(tmp_path):
    key = _key()
    _publish(tmp_path, key)
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, key, audit=sink)) as client:
        _load(client)
        _unload(client)

    [event] = [item for item in sink.recent() if item.action == "agent.unload"]
    assert event.status == "ok"
    assert event.target == "bot"


class FakeProvider:
    def __init__(self) -> None:
        self.principals = {
            "admin": Principal(tenant="acme", subject="admin", kind="human", roles=["admin"]),
            "viewer": Principal(tenant="local", subject="viewer", kind="human"),
        }

    async def resolve(self, credential: str) -> Principal:
        return self.principals[credential]


@needs_crypto
def test_cross_tenant_forbidden(tmp_path):
    key = _key()
    _publish(tmp_path, key)
    with TestClient(_app(tmp_path, key, oidc=FakeProvider())) as client:
        assert _load(client, headers={"Authorization": "Bearer admin"}).status_code == 200
        response = _unload(client, headers={"Authorization": "Bearer viewer"})

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


@needs_crypto
def test_swap_after_unload(tmp_path):
    key = _key()
    _publish(tmp_path, key, version="1.0.0")
    _publish(tmp_path, key, version="2.0.0")
    with TestClient(_app(tmp_path, key)) as client:
        assert _load(client, "1.0.0").status_code == 200
        assert _load(client, "2.0.0").status_code == 409
        assert _unload(client).status_code == 200
        swapped = _load(client, "2.0.0")

    assert swapped.status_code == 200
    assert swapped.json()["version"] == "2.0.0"
