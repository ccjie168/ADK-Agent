"""SLICE-291: in_process artifacts need a trusted builder signature at load time."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest

from adk_agent.core import AgentArtifact, AgentManifest, AgentRef, PublishedAgent
from adk_agent.registry import (
    ArtifactTrustError,
    TrustStore,
    pack_files,
    published_from,
    sign_digest,
)
from adk_agent.registry.loader import ArtifactLoadError, load_agent

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


def _key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _raw_hex(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return (
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )


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


class _BuilderTrust:
    def __init__(self) -> None:
        self.calls = 0

    def verify_builder(self, artifact: AgentArtifact) -> None:
        self.calls += 1


class _Loader:
    def __init__(self) -> None:
        self.calls = 0

    async def load(self, artifact: AgentArtifact, store) -> object:
        self.calls += 1
        return object()


class _Store:
    def __init__(self, data: bytes) -> None:
        self.calls = 0
        self.data = data

    async def get(self, digest: str) -> bytes:
        self.calls += 1
        return self.data


def _record(tier: str | None, builder_key=None, builder_key_id: str = "builder-1"):
    digest = "sha256:" + "a" * 64
    artifact = AgentArtifact(
        digest=digest,
        size=1,
        signature="00" * 64,
        key_id="publisher-1",
        builder_signature=sign_digest(digest, builder_key) if builder_key is not None else None,
        builder_key_id=builder_key_id if builder_key is not None else None,
    )
    manifest = AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier=tier,
    )
    return published_from(manifest, artifact=artifact)


def _load(record: PublishedAgent, *, builder_keys, loader=None, store=None):
    data = pack_files(
        {
            "manifest.json": record.manifest.model_dump_json().encode("utf-8"),
            "agent.py": b"",
        }
    )
    ref = AgentRef(id="bot", version="1.0.0", digest=record.digest)
    return asyncio.run(
        load_agent(
            registry=_Registry(record),
            ref=ref,
            tenant="acme",
            store=store or _Store(data),
            loader=loader or _Loader(),
            trust=_Trust(),
            builder_keys=builder_keys,
        )
    )


@needs_crypto
def test_load_rejects_an_in_process_artifact_without_builder_trust():
    builder = _key()
    store = _Store(
        pack_files(
            {
                "manifest.json": _record("in_process", builder)
                .manifest.model_dump_json()
                .encode("utf-8"),
                "agent.py": b"",
            }
        )
    )
    record = _record("in_process", builder)
    loader = _Loader()

    with pytest.raises(ArtifactLoadError) as exc:
        _load(record, builder_keys=None, loader=loader, store=store)

    assert "builder" in str(exc.value)
    assert loader.calls == 0
    assert store.calls == 0


@needs_crypto
def test_load_rejects_an_untrusted_builder_signature():
    builder = _key()
    attacker = _key()
    record = _record("in_process", builder)
    trust = TrustStore({"builder-1": bytes.fromhex(_raw_hex(attacker))})
    loader = _Loader()

    with pytest.raises(ArtifactTrustError) as exc:
        _load(record, builder_keys=trust, loader=loader)

    assert "builder" in str(exc.value)
    assert loader.calls == 0


@needs_crypto
def test_load_accepts_a_trusted_builder_signature():
    builder = _key()
    record = _record("in_process", builder)
    loader = _Loader()

    loaded = _load(
        record,
        builder_keys=TrustStore({"builder-1": bytes.fromhex(_raw_hex(builder))}),
        loader=loader,
    )

    assert loaded is not None
    assert loader.calls == 1


@needs_crypto
def test_load_does_not_require_builder_trust_for_sandboxed():
    from adk_agent.sandbox.agent import SandboxResult, set_agent_sandbox_backend

    class _Backend:
        async def run(self, artifact, data, input_text, *, manifest=None):
            return SandboxResult(text="stub")

    builder_trust = _BuilderTrust()
    set_agent_sandbox_backend(_Backend())
    try:
        for builder_keys in (None, builder_trust):
            loaded = _load(_record("sandboxed"), builder_keys=builder_keys)
            assert type(loaded).__name__ == "SandboxAgent"
    finally:
        set_agent_sandbox_backend(None)

    assert builder_trust.calls == 0
