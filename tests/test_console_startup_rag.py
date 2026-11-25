"""SLICE-204: console startup refs carry their manifest into retrieval wiring."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import AgentArtifact, AgentManifest
from adk_agent.registry import (
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    TrustStore,
    artifact_digest,
    load_registry_agents,
    pack_agent,
    published_from,
    sign_digest,
)

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


def _published(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    raw_hex = (
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    project = tmp_path / "project"
    project.mkdir()
    manifest = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
        "rag": {"enabled": True, "top_k": 3},
    }
    (project / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
        signature=sign_digest(digest, key),
        key_id="k1",
        builder_signature=sign_digest(digest, key),
        builder_key_id="k1",
    )
    store = FileArtifactStore(tmp_path / "store")
    asyncio.run(store.put(artifact, data))
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(
        registry.publish(published_from(AgentManifest.model_validate(manifest), artifact=artifact))
    )
    trust = TrustStore({"k1": bytes.fromhex(raw_hex)})
    return store, registry, trust


class RecordingRag:
    """Stands in for RagFactory; records which manifests reached context()."""

    def __init__(self) -> None:
        self.manifests: list[AgentManifest] = []

    def context(self, manifest: AgentManifest) -> object:
        self.manifests.append(manifest)
        return object()


def _agent(name: str) -> LlmAgent:
    return LlmAgent(name=name, model="gemini-2.5-pro", instruction="x")


@needs_crypto
def test_registry_ref_agent_carries_its_manifest(tmp_path):
    store, registry, trust = _published(tmp_path)
    agents = asyncio.run(
        load_registry_agents(
            ["acme/bot@1.0.0"],
            registry=registry,
            store=store,
            trust=trust,
            builder_keys=trust,
            loader=InProcessArtifactLoader(),
        )
    )
    manifest = getattr(agents["bot"], "_adk_manifest", None)
    assert isinstance(manifest, AgentManifest)
    assert manifest.id == "bot"
    assert manifest.rag is not None and manifest.rag.enabled is True


def test_console_startup_agent_gets_rag_context():
    agent = _agent("bot")
    manifest = AgentManifest.model_validate(
        {
            "id": "bot",
            "version": "1.0.0",
            "tenant": "acme",
            "owner": "acme",
            "model_policy": {"provider_allowlist": ["litellm"]},
            "rag": {"enabled": True},
        }
    )
    object.__setattr__(agent, "_adk_manifest", manifest)
    rag = RecordingRag()
    build_console_app({"bot": agent}, auth_token="secret", rag=rag)
    assert rag.manifests == [manifest]


def test_console_file_loaded_agent_stays_without_rag():
    rag = RecordingRag()
    build_console_app({"bot": _agent("bot")}, auth_token="secret", rag=rag)
    assert rag.manifests == []
