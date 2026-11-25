"""SLICE-123: composed agents publish and load as plain versions."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest

from adk_agent.compose import compose_and_publish
from adk_agent.core import AgentRef
from adk_agent.registry import (
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    RegistryConflict,
    TrustStore,
    load_agent,
)

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


def _key(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    path = tmp_path / "publisher.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    raw = (
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    return key, path, raw


def _publish(tmp_path, key, *, instruction: str = "You are helpful.", tools=("ping",)):
    registry = FileAgentRegistry(tmp_path / "registry")
    store = FileArtifactStore(tmp_path / "artifacts")
    published = asyncio.run(
        compose_and_publish(
            template_id="single-llm",
            name="assistant",
            version="1.0.0",
            tenant="acme",
            instruction=instruction,
            tools=tools,
            data_classes=("internal",),
            registry=registry,
            artifact_store=store,
            private_key=key,
            key_id="publisher-1",
            builder_key=key,
            builder_key_id="builder-1",
        )
    )
    return published, registry, store


@needs_crypto
def test_composed_agent_loads(tmp_path, monkeypatch):
    from google.adk.agents import LlmAgent

    monkeypatch.setenv("ADK_AGENT_MODEL", "gemini:gemini-2.5-pro")
    key, _, raw = _key(tmp_path)
    published, registry, store = _publish(tmp_path, key)
    ref = AgentRef(id="assistant", version="1.0.0", digest=published.digest)

    agent = asyncio.run(
        load_agent(
            registry=registry,
            ref=ref,
            tenant="acme",
            store=store,
            loader=InProcessArtifactLoader(),
            trust=TrustStore({"publisher-1": bytes.fromhex(raw)}),
            builder_keys=TrustStore({"builder-1": bytes.fromhex(raw)}),
        )
    )

    assert isinstance(agent, LlmAgent)
    assert agent.name == "assistant"
    assert agent.instruction == "You are helpful."
    assert any(getattr(tool, "__name__", None) == "ping" for tool in agent.tools)


@needs_crypto
def test_compose_publishes_a_plain_version(tmp_path):
    key, _, _ = _key(tmp_path)
    published, registry, store = _publish(tmp_path, key)

    assert published.artifact is not None
    assert published.artifact.signature is not None
    assert published.artifact.key_id == "publisher-1"
    assert published.manifest.exposure == "none"
    assert [grant.tool_id for grant in published.manifest.tool_grants] == ["ping"]
    assert asyncio.run(store.get(published.artifact.digest)) is not None

    again, _, _ = _publish(tmp_path, key)
    assert again.digest == published.digest

    with pytest.raises(RegistryConflict):
        _publish(tmp_path, key, instruction="A completely different instruction.")


@needs_crypto
def test_compose_requires_a_builder_key(tmp_path):
    from adk_agent.compose import ComposeError
    from adk_agent.registry import FileAgentRegistry, FileArtifactStore

    key = _key(tmp_path)
    with pytest.raises(ComposeError):
        asyncio.run(
            compose_and_publish(
                template_id="single-llm",
                name="assistant",
                version="1.0.0",
                tenant="acme",
                instruction="You are helpful.",
                registry=FileAgentRegistry(tmp_path / "registry"),
                artifact_store=FileArtifactStore(tmp_path / "artifacts"),
                private_key=key,
                key_id="publisher-1",
            )
        )
