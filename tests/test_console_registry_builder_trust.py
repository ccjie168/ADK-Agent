"""SLICE-291: the console refuses to run unsigned in_process artifacts."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import AgentArtifact, AgentManifest
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


def _manifest() -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="in_process",
    )


def _publish(tmp_path, publisher, builder):
    project = tmp_path / "project"
    project.mkdir()
    (project / "manifest.json").write_text(_manifest().model_dump_json(), encoding="utf-8")
    (project / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        "agent = LlmAgent(name='bot', model='gemini-2.5-pro', instruction='x')\n",
        encoding="utf-8",
    )
    data = pack_agent(project)
    digest = artifact_digest(data)
    artifact = AgentArtifact(
        digest=digest,
        size=len(data),
        signature=sign_digest(digest, publisher),
        key_id="k1",
        builder_signature=sign_digest(digest, builder),
        builder_key_id="b1",
    )
    asyncio.run(FileArtifactStore(tmp_path / "store").put(artifact, data))
    asyncio.run(
        FileAgentRegistry(tmp_path / "registry").publish(
            published_from(_manifest(), artifact=artifact)
        )
    )


def _app(tmp_path, publisher, *, builder_trust=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=["admin"],
        registry=FileAgentRegistry(tmp_path / "registry"),
        artifact_store=FileArtifactStore(tmp_path / "store"),
        artifact_loader=InProcessArtifactLoader(),
        artifact_trust=TrustStore({"k1": _raw(publisher)}),
        builder_keys=builder_trust,
    )


def _load(client):
    return client.post(
        "/api/registry/load", json={"tenant": "acme", "id": "bot", "version": "1.0.0"}, headers=AUTH
    )


@needs_crypto
def test_registry_load_requires_builder_trust(tmp_path):
    publisher, builder = _key(), _key()
    _publish(tmp_path, publisher, builder)

    with TestClient(_app(tmp_path, publisher)) as client:
        response = _load(client)
        agents = client.get("/api/agents", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"error": "builder_trust_unavailable"}
    assert [item["name"] for item in agents.json()] == ["probe"]


@needs_crypto
def test_registry_load_accepts_builder_trust(tmp_path):
    publisher, builder = _key(), _key()
    _publish(tmp_path, publisher, builder)

    with TestClient(
        _app(tmp_path, publisher, builder_trust=TrustStore({"b1": _raw(builder)}))
    ) as c:
        response = _load(c)
        agents = c.get("/api/agents", headers=AUTH)

    assert response.status_code == 200
    assert sorted(item["name"] for item in agents.json()) == ["bot", "probe"]


@needs_crypto
def test_registry_load_rejects_an_untrusted_builder(tmp_path):
    publisher, builder, other = _key(), _key(), _key()
    _publish(tmp_path, publisher, builder)

    with TestClient(_app(tmp_path, publisher, builder_trust=TrustStore({"b1": _raw(other)}))) as c:
        response = _load(c)

    assert response.status_code == 409
    assert response.json() == {"error": "artifact_untrusted"}
