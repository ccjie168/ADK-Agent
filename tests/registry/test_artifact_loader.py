"""SLICE-067: verified in-process artifact loading."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from adk_agent.core import AgentArtifact, AgentManifest, AgentRef
from adk_agent.registry import (
    ArtifactLoadError,
    ArtifactTrustError,
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    TrustStore,
    artifact_digest,
    load_agent,
    pack_agent,
    published_from,
    sign_digest,
)

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")

MANIFEST = {
    "id": "bot",
    "version": "1.0.0",
    "tenant": "acme",
    "owner": "acme",
    "model_policy": {"provider_allowlist": ["litellm"]},
}
AGENT_SOURCE = (
    "from google.adk.agents import LlmAgent\n"
    "agent = LlmAgent(name='bot', model='gemini-2.5-pro', instruction='x')\n"
)


def _project(tmp_path, *, source: str = AGENT_SOURCE, manifest: dict | None = None) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    (project / "manifest.json").write_text(
        json.dumps(MANIFEST if manifest is None else manifest), encoding="utf-8"
    )
    (project / "agent.py").write_text(source, encoding="utf-8")
    return project


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


def _trust(key, kid: str = "k1") -> TrustStore:
    return TrustStore({kid: bytes.fromhex(_raw_hex(key))})


def _signed(data: bytes, key, *, kid: str = "k1", signature: str | None = None):
    digest = artifact_digest(data)
    return AgentArtifact(
        digest=digest,
        size=len(data),
        signature=sign_digest(digest, key) if signature is None else signature,
        key_id=kid,
    )


def _zip(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
        if symlink is not None:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def _fix(artifact: AgentArtifact, data: bytes) -> AgentArtifact:
    digest = artifact_digest(data)
    return artifact.model_copy(
        update={"digest": digest, "size": len(data), "signature": artifact.signature}
    )


@needs_crypto
def test_trust_verifies(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))

    _trust(key).verify(_signed(data, key))


@needs_crypto
def test_trust_unknown_key(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))

    with pytest.raises(ArtifactTrustError):
        _trust(_key(), kid="other").verify(_signed(data, key))


@needs_crypto
def test_trust_requires_signature(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))
    artifact = AgentArtifact(digest=artifact_digest(data), size=len(data), key_id="k1")

    with pytest.raises(ArtifactTrustError):
        _trust(key).verify(artifact)


@needs_crypto
def test_trust_rejects_tamper(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))
    artifact = _signed(data, key)
    bad = "0" + artifact.signature[1:] if artifact.signature else "0" * 128

    with pytest.raises(ArtifactTrustError):
        _trust(key).verify(artifact.model_copy(update={"signature": bad}))


@needs_crypto
def test_loads_agent(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))
    store = FileArtifactStore(tmp_path / "store")
    artifact = _signed(data, key)
    asyncio.run(store.put(artifact, data))

    agent = asyncio.run(InProcessArtifactLoader().load(artifact, store))

    assert agent.name == "bot"


@needs_crypto
def test_missing_bytes(tmp_path):
    key = _key()
    artifact = _signed(b"not-stored", key)

    with pytest.raises(ArtifactLoadError):
        asyncio.run(InProcessArtifactLoader().load(artifact, FileArtifactStore(tmp_path / "store")))


@needs_crypto
def test_digest_mismatch(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))
    artifact = _signed(data, key)
    store = FileArtifactStore(tmp_path / "store")
    target = store.root / "sha256" / artifact.digest.split(":", 1)[1]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different bytes")

    with pytest.raises(ArtifactLoadError):
        asyncio.run(InProcessArtifactLoader().load(artifact, store))


def _load_zip(tmp_path, data: bytes, artifact: AgentArtifact):
    store = FileArtifactStore(tmp_path / "store")
    asyncio.run(store.put(artifact, data))
    return asyncio.run(InProcessArtifactLoader().load(artifact, store))


@needs_crypto
def test_rejects_traversal(tmp_path):
    key = _key()
    data = _zip(
        {
            "manifest.json": json.dumps(MANIFEST).encode(),
            "agent.py": AGENT_SOURCE.encode(),
            "../evil.py": b"x = 1",
        }
    )
    artifact = _fix(_signed(b"x", key), data)

    with pytest.raises(ArtifactLoadError):
        _load_zip(tmp_path, data, artifact)


@needs_crypto
def test_rejects_absolute(tmp_path):
    key = _key()
    data = _zip(
        {
            "manifest.json": json.dumps(MANIFEST).encode(),
            "agent.py": AGENT_SOURCE.encode(),
            "/evil.py": b"x = 1",
        }
    )
    artifact = _fix(_signed(b"x", key), data)

    with pytest.raises(ArtifactLoadError):
        _load_zip(tmp_path, data, artifact)


@needs_crypto
def test_rejects_symlink(tmp_path):
    key = _key()
    data = _zip(
        {"manifest.json": json.dumps(MANIFEST).encode(), "agent.py": AGENT_SOURCE.encode()},
        symlink="link.py",
    )
    artifact = _fix(_signed(b"x", key), data)

    with pytest.raises(ArtifactLoadError):
        _load_zip(tmp_path, data, artifact)


@needs_crypto
def test_rejects_unexpected_file(tmp_path):
    key = _key()
    data = _zip(
        {
            "manifest.json": json.dumps(MANIFEST).encode(),
            "agent.py": AGENT_SOURCE.encode(),
            "extra.py": b"x = 1",
        }
    )
    artifact = _fix(_signed(b"x", key), data)

    with pytest.raises(ArtifactLoadError):
        _load_zip(tmp_path, data, artifact)


@needs_crypto
def test_rejects_missing_entrypoint(tmp_path):
    key = _key()
    data = _zip({"manifest.json": json.dumps(MANIFEST).encode()})
    artifact = _fix(_signed(b"x", key), data)

    with pytest.raises(ArtifactLoadError):
        _load_zip(tmp_path, data, artifact)


def _load_source(tmp_path, source: str):
    key = _key()
    data = _zip({"manifest.json": json.dumps(MANIFEST).encode(), "agent.py": source.encode()})
    artifact = _fix(_signed(b"x", key), data)
    return _load_zip(tmp_path, data, artifact)


@needs_crypto
def test_rejects_name_mismatch(tmp_path):
    source = (
        "from google.adk.agents import LlmAgent\n"
        "agent = LlmAgent(name='other', model='gemini-2.5-pro', instruction='x')\n"
    )

    with pytest.raises(ArtifactLoadError):
        _load_source(tmp_path, source)


@needs_crypto
def test_rejects_no_agent(tmp_path):
    with pytest.raises(ArtifactLoadError):
        _load_source(tmp_path, "x = 1\n")


def _published(tmp_path, key, data):
    artifact = _signed(data, key)
    store = FileArtifactStore(tmp_path / "store")
    asyncio.run(store.put(artifact, data))
    manifest = AgentManifest.model_validate(MANIFEST)
    published = published_from(manifest, artifact=artifact)
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published))
    return published, store, registry


@needs_crypto
def test_load_agent(tmp_path):
    key = _key()
    data = pack_agent(_project(tmp_path))
    published, store, registry = _published(tmp_path, key, data)
    ref = AgentRef(id="bot", version="1.0.0", digest=published.digest)

    agent = asyncio.run(
        load_agent(
            registry=registry,
            ref=ref,
            tenant="acme",
            store=store,
            loader=InProcessArtifactLoader(),
            trust=_trust(key),
        )
    )

    assert agent.name == "bot"
    with pytest.raises(ArtifactTrustError):
        asyncio.run(
            load_agent(
                registry=registry,
                ref=ref,
                tenant="acme",
                store=store,
                loader=InProcessArtifactLoader(),
                trust=_trust(_key()),
            )
        )


@needs_crypto
def test_load_agent_without_artifact(tmp_path):
    manifest = AgentManifest.model_validate(MANIFEST)
    published = published_from(manifest)
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published))
    ref = AgentRef(id="bot", version="1.0.0", digest=published.digest)

    with pytest.raises(ArtifactLoadError):
        asyncio.run(
            load_agent(
                registry=registry,
                ref=ref,
                tenant="acme",
                store=FileArtifactStore(tmp_path / "store"),
                loader=InProcessArtifactLoader(),
                trust=TrustStore({}),
            )
        )
