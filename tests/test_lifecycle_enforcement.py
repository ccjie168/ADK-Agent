"""SLICE-077: retired versions cannot be loaded, and the CLI changes state."""

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
    FileAgentLifecycleStore,
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    RefError,
    TrustStore,
    artifact_digest,
    load_registry_agents,
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


def _raw_hex(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return (
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )


def _published(tmp_path, key, *, version="1.0.0"):
    project = tmp_path / f"project-{version}"
    project.mkdir()
    manifest = {
        "id": "bot",
        "version": version,
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
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
    published = published_from(AgentManifest.model_validate(manifest), artifact=artifact)
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published))
    return store, registry


def _lifecycle(tmp_path) -> FileAgentLifecycleStore:
    return FileAgentLifecycleStore(tmp_path / "registry")


def _trust(key) -> TrustStore:
    return TrustStore({"k1": bytes.fromhex(_raw_hex(key))})


def _retire(tmp_path, status="retired"):
    asyncio.run(
        _lifecycle(tmp_path).set(
            "acme", "bot", "1.0.0", status=status, changed_by="ops", reason="test"
        )
    )


@needs_crypto
def test_ref_load_refuses_retired(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)
    _retire(tmp_path)

    with pytest.raises(RefError, match="retired"):
        asyncio.run(
            load_registry_agents(
                ["acme/bot@1.0.0"],
                registry=registry,
                store=store,
                trust=_trust(key),
                builder_keys=_trust(key),
                lifecycle=_lifecycle(tmp_path),
            )
        )


@needs_crypto
def test_ref_load_allows_deprecated(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)
    _retire(tmp_path, status="deprecated")

    agents = asyncio.run(
        load_registry_agents(
            ["acme/bot@1.0.0"],
            registry=registry,
            store=store,
            trust=_trust(key),
            builder_keys=_trust(key),
            lifecycle=_lifecycle(tmp_path),
        )
    )

    assert agents["bot"].name == "bot"


@needs_crypto
def test_console_load_refuses_retired(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)
    _retire(tmp_path)
    probe = LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")
    app = build_console_app(
        {"probe": probe},
        auth_token="secret",
        roles=["admin"],
        registry=registry,
        artifact_store=store,
        artifact_loader=InProcessArtifactLoader(),
        artifact_trust=_trust(key),
        lifecycle=_lifecycle(tmp_path),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/registry/load",
            json={"tenant": "acme", "id": "bot", "version": "1.0.0"},
            headers=AUTH,
        )

    assert response.status_code == 409
    assert response.json() == {"error": "version_retired"}


@needs_crypto
def test_registry_listing_includes_lifecycle(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)
    _retire(tmp_path, status="deprecated")
    app = build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=["admin"],
        registry=registry,
        lifecycle=_lifecycle(tmp_path),
    )
    with TestClient(app) as client:
        [entry] = client.get("/api/registry?tenant=acme", headers=AUTH).json()

    assert entry["lifecycle"]["status"] == "deprecated"


def test_cli_lifecycle_set_file(tmp_path, capsys):
    registry = tmp_path / "registry"
    manifest = AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
    )
    asyncio.run(FileAgentRegistry(registry).publish(published_from(manifest)))

    cli.main(
        [
            "lifecycle",
            "set",
            "--registry",
            str(registry),
            "--tenant",
            "acme",
            "--id",
            "bot",
            "--version",
            "1.0.0",
            "--status",
            "retired",
            "--reason",
            "bad build",
        ]
    )

    state = asyncio.run(FileAgentLifecycleStore(registry).get("acme", "bot", "1.0.0"))
    assert state.status == "retired"
    assert state.reason == "bad build"
    assert "acme/bot@1.0.0 status=retired" in capsys.readouterr().out


def test_cli_lifecycle_set_http(tmp_path, monkeypatch, capsys):
    calls: list = []

    class FakeRegistry:
        def __init__(self, url, *, auth_token=None, **_kwargs):
            self.url = url
            self.auth_token = auth_token

        async def set_lifecycle(self, tenant, agent_id, version, status, reason=""):
            from adk_agent.core import AgentLifecycle

            calls.append((tenant, agent_id, version, status, reason))
            return AgentLifecycle(status=status, changed_by="alice", reason=reason)

        async def aclose(self):
            pass

    monkeypatch.setattr("adk_agent.registry.HttpAgentRegistry", FakeRegistry)

    cli.main(
        [
            "lifecycle",
            "set",
            "--registry-url",
            "http://reg.example",
            "--tenant",
            "acme",
            "--id",
            "bot",
            "--version",
            "1.0.0",
            "--status",
            "deprecated",
            "--reason",
            "old",
        ]
    )

    assert calls == [("acme", "bot", "1.0.0", "deprecated", "old")]
    assert "acme/bot@1.0.0 status=deprecated" in capsys.readouterr().out


def test_cli_rejects_bad_status(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "lifecycle",
                "set",
                "--registry",
                str(tmp_path / "registry"),
                "--tenant",
                "acme",
                "--id",
                "bot",
                "--version",
                "1.0.0",
                "--status",
                "deleted",
            ]
        )

    assert exc.value.code == 1
    assert "status" in capsys.readouterr().err.lower()
