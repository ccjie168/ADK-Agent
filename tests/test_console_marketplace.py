"""SLICE-069: the registry listing shows artifact trust status."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.console import build_console_app
from adk_agent.core import AgentArtifact, AgentManifest
from adk_agent.registry import (
    FileAgentRegistry,
    TrustStore,
    artifact_digest,
    published_from,
    sign_digest,
)

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")

AUTH = {"Authorization": "Bearer secret"}


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


def _manifest() -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        description="support bot",
        model_policy={"provider_allowlist": ["litellm"]},
    )


def _artifact(key=None, *, signed: bool = True) -> AgentArtifact:
    data = b"zip-bytes"
    digest = artifact_digest(data)
    return AgentArtifact(
        digest=digest,
        size=len(data),
        signature=sign_digest(digest, key) if signed and key is not None else None,
        key_id="k1" if signed and key is not None else None,
    )


def _populate(tmp_path, artifact: AgentArtifact | None):
    record = published_from(_manifest(), artifact=artifact)
    asyncio.run(FileAgentRegistry(tmp_path).publish(record))
    return tmp_path


def _app(tmp_path, *, trust: TrustStore | None = None):
    return build_console_app(
        {
            "probe": LlmAgent(
                name="probe",
                model="gemini-2.5-pro",
                description="probe",
                instruction="x",
            )
        },
        auth_token="secret",
        registry=FileAgentRegistry(tmp_path),
        artifact_trust=trust,
    )


def _entry(tmp_path, *, trust: TrustStore | None):
    with TestClient(_app(tmp_path, trust=trust)) as client:
        response = client.get("/api/registry?tenant=acme", headers=AUTH)

    assert response.status_code == 200
    [entry] = response.json()
    return entry


@needs_crypto
def test_listing_includes_verified_artifact(tmp_path):
    key = _key()
    artifact = _artifact(key)
    _populate(tmp_path, artifact)

    entry = _entry(tmp_path, trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}))

    assert entry["artifact"] == {
        "digest": artifact.digest,
        "size": artifact.size,
        "key_id": "k1",
        "status": "verified",
    }


@needs_crypto
def test_untrusted_status(tmp_path):
    _populate(tmp_path, _artifact(_key()))

    entry = _entry(tmp_path, trust=TrustStore({"k1": bytes.fromhex(_raw_hex(_key()))}))

    assert entry["artifact"]["status"] == "untrusted"


@needs_crypto
def test_unknown_without_trust(tmp_path):
    _populate(tmp_path, _artifact(_key()))

    entry = _entry(tmp_path, trust=None)

    assert entry["artifact"]["status"] == "unknown"


@needs_crypto
def test_unsigned_status(tmp_path):
    _populate(tmp_path, _artifact(None, signed=False))

    entry = _entry(tmp_path, trust=TrustStore({}))

    assert entry["artifact"]["status"] == "unsigned"


def test_no_artifact(tmp_path):
    _populate(tmp_path, None)

    entry = _entry(tmp_path, trust=None)

    assert entry["artifact"] is None


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


@needs_crypto
def test_cli_wires_trust(tmp_path, monkeypatch):
    key = _key()
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"k1": _raw_hex(key)}), encoding="utf-8")
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(["console", "--agents", _agents_file(tmp_path), "--artifact-keys", str(keys)])

    assert captured["artifact_trust"] is not None


def test_cli_rejects_bad_keys(tmp_path, monkeypatch, capsys):
    keys = tmp_path / "keys.json"
    keys.write_text("not json", encoding="utf-8")
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["console", "--agents", _agents_file(tmp_path), "--artifact-keys", str(keys)])

    assert exc.value.code == 1
    assert "artifact" in capsys.readouterr().err.lower()
