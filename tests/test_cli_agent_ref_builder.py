"""SLICE-291: registry loads under --agent-ref enforce the builder signature."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest

from adk_agent import cli
from adk_agent.core import AgentArtifact, AgentManifest
from adk_agent.registry import (
    FileAgentRegistry,
    FileArtifactStore,
    artifact_digest,
    pack_agent,
    published_from,
    sign_digest,
)

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


def _published(tmp_path, publisher, builder):
    project = tmp_path / "project"
    project.mkdir()
    manifest = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
        "execution_tier": "in_process",
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
        signature=sign_digest(digest, publisher),
        key_id="p1",
        builder_signature=sign_digest(digest, builder),
        builder_key_id="b1",
    )
    store = FileArtifactStore(tmp_path / "store")
    asyncio.run(store.put(artifact, data))
    asyncio.run(
        FileAgentRegistry(tmp_path / "registry").publish(
            published_from(AgentManifest.model_validate(manifest), artifact=artifact)
        )
    )


def _args(tmp_path) -> list[str]:
    return [
        "--agent-ref",
        "acme/bot@1.0.0",
        "--registry",
        str(tmp_path / "registry"),
        "--artifact-dir",
        str(tmp_path / "store"),
    ]


@needs_crypto
def test_console_refuses_in_process_without_builder_keys(tmp_path, monkeypatch, capsys):
    publisher, builder = _key(), _key()
    _published(tmp_path, publisher, builder)
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"p1": _raw_hex(publisher)}))
    monkeypatch.delenv("ADK_BUILDER_KEYS", raising=False)
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["console", *_args(tmp_path)])

    assert exc.value.code == 1
    assert "builder" in capsys.readouterr().err


@needs_crypto
def test_console_refuses_an_untrusted_builder_key(tmp_path, monkeypatch, capsys):
    publisher, builder, other = _key(), _key(), _key()
    _published(tmp_path, publisher, builder)
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"p1": _raw_hex(publisher)}))
    monkeypatch.setenv("ADK_BUILDER_KEYS", json.dumps({"b1": _raw_hex(other)}))
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["console", *_args(tmp_path)])

    assert exc.value.code == 1
    assert "builder" in capsys.readouterr().err


def _builder_file(tmp_path, builder) -> str:
    path = tmp_path / "builder-keys.json"
    path.write_text(json.dumps({"b1": _raw_hex(builder)}), encoding="utf-8")
    return str(path)


@needs_crypto
def test_serve_accepts_builder_keys(tmp_path, monkeypatch):
    publisher, builder = _key(), _key()
    _published(tmp_path, publisher, builder)
    captured: dict = {}
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"p1": _raw_hex(publisher)}))
    monkeypatch.delenv("ADK_BUILDER_KEYS", raising=False)
    monkeypatch.setattr("adk_agent.mcp.server.serve_agent", lambda **k: captured.update(k))

    cli.main(["serve", *_args(tmp_path), "--builder-keys", _builder_file(tmp_path, builder)])

    assert captured["agent"].name == "bot"


@needs_crypto
def test_serve_many_accepts_builder_keys(tmp_path, monkeypatch):
    publisher, builder = _key(), _key()
    _published(tmp_path, publisher, builder)
    captured: dict = {}
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"p1": _raw_hex(publisher)}))
    monkeypatch.delenv("ADK_BUILDER_KEYS", raising=False)
    monkeypatch.setattr("adk_agent.mcp.server.serve_many", lambda **k: captured.update(k))

    cli.main(["serve-many", *_args(tmp_path), "--builder-keys", _builder_file(tmp_path, builder)])

    assert captured["agents"]["bot"].name == "bot"


@needs_crypto
def test_serve_a2a_accepts_builder_keys(tmp_path, monkeypatch):
    publisher, builder = _key(), _key()
    _published(tmp_path, publisher, builder)
    captured: dict = {}
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"p1": _raw_hex(publisher)}))
    monkeypatch.delenv("ADK_BUILDER_KEYS", raising=False)
    monkeypatch.setattr("adk_agent.a2a.serve_a2a", lambda **k: captured.update(k))

    cli.main(["serve-a2a", *_args(tmp_path), "--builder-keys", _builder_file(tmp_path, builder)])

    assert captured["agent"].name == "bot"


@pytest.mark.parametrize(
    "command", ["serve", "serve-many", "serve-a2a", "console", "serve-triggers"]
)
def test_every_ref_command_exposes_builder_keys(command, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])

    assert exc.value.code == 0
    assert "--builder-keys" in capsys.readouterr().out
