"""SLICE-123: the templates and compose CLI commands."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest

from adk_agent import cli
from adk_agent.core import AgentRef, PublishedAgent
from adk_agent.registry import (
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
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


def _compose_args(tmp_path, key_path, *, template="single-llm", name="assistant"):
    return [
        "compose",
        "--template",
        template,
        "--tenant",
        "acme",
        "--id",
        name,
        "--version",
        "1.0.0",
        "--instruction",
        "You are helpful.",
        "--tools",
        "ping",
        "--data-classes",
        "internal",
        "--key",
        str(key_path),
        "--key-id",
        "publisher-1",
        "--builder-key",
        str(key_path),
        "--builder-key-id",
        "builder-1",
        "--registry",
        str(tmp_path / "registry"),
        "--artifact-dir",
        str(tmp_path / "artifacts"),
    ]


@needs_crypto
def test_cli_compose_and_templates(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ARTIFACT_URL", raising=False)
    monkeypatch.setenv("ADK_AGENT_MODEL", "gemini:gemini-2.5-pro")
    cli.main(["templates"])
    templates = json.loads(capsys.readouterr().out)
    assert [template["template_id"] for template in templates] == ["single-llm"]

    key, key_path, raw = _key(tmp_path)
    cli.main(_compose_args(tmp_path, key_path))
    out = capsys.readouterr().out
    assert "composed acme/assistant@1.0.0 sha256:" in out
    assert "artifact sha256:" in out

    record_path = tmp_path / "registry" / "acme" / "assistant" / "1.0.0.json"
    record = PublishedAgent.model_validate_json(record_path.read_text(encoding="utf-8"))
    agent = asyncio.run(
        load_agent(
            registry=FileAgentRegistry(tmp_path / "registry"),
            ref=AgentRef(id="assistant", version="1.0.0", digest=record.digest),
            tenant="acme",
            store=FileArtifactStore(tmp_path / "artifacts"),
            loader=InProcessArtifactLoader(),
            trust=TrustStore({"publisher-1": bytes.fromhex(raw)}),
        )
    )

    assert agent.name == "assistant"
    assert agent.instruction == "You are helpful."
    assert any(getattr(tool, "__name__", None) == "ping" for tool in agent.tools)


@needs_crypto
def test_cli_compose_errors(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ARTIFACT_URL", raising=False)
    _, key_path, _ = _key(tmp_path)

    missing = _compose_args(tmp_path, key_path)
    missing.remove("--key")
    missing.remove(str(key_path))
    with pytest.raises(SystemExit) as exc:
        cli.main(missing)
    assert exc.value.code == 1
    assert "compose failed: --key and --key-id are required" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        cli.main(_compose_args(tmp_path, key_path, template="nope"))
    assert exc.value.code == 1
    assert "compose failed:" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        cli.main(_compose_args(tmp_path, key_path, name="my-agent"))
    assert exc.value.code == 1
    assert "compose failed:" in capsys.readouterr().err
