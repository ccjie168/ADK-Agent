"""SLICE-068: start the console and MCP from registry references."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json

import pytest

from adk_agent import cli
from adk_agent.core import AgentArtifact, AgentManifest
from adk_agent.registry import (
    ArtifactLoadError,
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    RefError,
    TrustStore,
    artifact_digest,
    load_registry_agents,
    pack_agent,
    parse_agent_ref,
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


def _published(
    tmp_path,
    key,
    *,
    tenant="acme",
    name="bot",
    version="1.0.0",
    execution_tier=None,
    tool_grants=None,
):
    project = tmp_path / f"project-{tenant}-{version}"
    project.mkdir()
    manifest = {
        "id": name,
        "version": version,
        "tenant": tenant,
        "owner": tenant,
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    if execution_tier is not None:
        manifest["execution_tier"] = execution_tier
    if tool_grants is not None:
        manifest["tool_grants"] = tool_grants
    (project / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (project / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        f"agent = LlmAgent(name='{name}', model='gemini-2.5-pro', instruction='x')\n",
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
        builder_key_id="b1",
    )
    store = FileArtifactStore(tmp_path / "store")
    asyncio.run(store.put(artifact, data))
    published = published_from(AgentManifest.model_validate(manifest), artifact=artifact)
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published))
    return store, registry


def test_parse_agent_ref():
    assert parse_agent_ref("acme/bot@1.0.0") == ("acme", "bot", "1.0.0")


@pytest.mark.parametrize(
    "text",
    ["acme/bot", "bot@1.0.0", "acme/bot@", "../x/bot@1", "acme/bot@1/2", "acme//bot@1"],
)
def test_parse_rejects_bad_ref(text):
    with pytest.raises(RefError):
        parse_agent_ref(text)


@needs_crypto
def test_load_registry_agents(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)

    agents = asyncio.run(
        load_registry_agents(
            ["acme/bot@1.0.0"],
            registry=registry,
            store=store,
            trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}),
            builder_keys=TrustStore({"b1": bytes.fromhex(_raw_hex(key))}),
            loader=InProcessArtifactLoader(),
        )
    )

    assert list(agents) == ["bot"]
    assert agents["bot"].name == "bot"


@needs_crypto
def test_unknown_version(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)

    with pytest.raises(ArtifactLoadError):
        asyncio.run(
            load_registry_agents(
                ["acme/bot@9.9.9"],
                registry=registry,
                store=store,
                trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}),
                loader=InProcessArtifactLoader(),
            )
        )


@needs_crypto
def test_duplicate_name(tmp_path):
    key = _key()
    store, registry = _published(tmp_path, key)
    _published(tmp_path, key, tenant="other")

    with pytest.raises(RefError):
        asyncio.run(
            load_registry_agents(
                ["acme/bot@1.0.0", "other/bot@1.0.0"],
                registry=registry,
                store=store,
                trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}),
                builder_keys=TrustStore({"b1": bytes.fromhex(_raw_hex(key))}),
                loader=InProcessArtifactLoader(),
            )
        )


def _common_args(tmp_path, key, *refs) -> list[str]:
    return [
        *sum((["--agent-ref", ref] for ref in refs), []),
        "--registry",
        str(tmp_path / "registry"),
        "--artifact-dir",
        str(tmp_path / "store"),
    ]


@needs_crypto
def test_console_loads_from_registry(tmp_path, monkeypatch):
    key = _key()
    _published(tmp_path, key)
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"k1": _raw_hex(key)}))
    monkeypatch.setenv("ADK_BUILDER_KEYS", json.dumps({"b1": _raw_hex(key)}))

    cli.main(["console", *_common_args(tmp_path, key, "acme/bot@1.0.0")])

    assert list(captured["agents"]) == ["bot"]


@needs_crypto
def test_serve_loads_from_registry(tmp_path, monkeypatch):
    key = _key()
    _published(tmp_path, key)
    captured: dict = {}
    monkeypatch.setattr("adk_agent.mcp.server.serve_agent", lambda **k: captured.update(k))
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"k1": _raw_hex(key)}))
    monkeypatch.setenv("ADK_BUILDER_KEYS", json.dumps({"b1": _raw_hex(key)}))

    cli.main(["serve", *_common_args(tmp_path, key, "acme/bot@1.0.0")])

    assert captured["agent"].name == "bot"


@needs_crypto
def test_sources_are_exclusive(tmp_path, monkeypatch, capsys):
    key = _key()
    _published(tmp_path, key)
    agents_file = tmp_path / "agents.py"
    agents_file.write_text("agents = {}\n", encoding="utf-8")
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"k1": _raw_hex(key)}))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                str(agents_file),
                *_common_args(tmp_path, key, "acme/bot@1.0.0"),
            ]
        )

    assert exc.value.code == 1


@needs_crypto
def test_missing_artifact_config(tmp_path, monkeypatch, capsys):
    key = _key()
    _published(tmp_path, key)
    monkeypatch.delenv("ADK_ARTIFACT_KEYS", raising=False)
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["console", *_common_args(tmp_path, key, "acme/bot@1.0.0")])

    assert exc.value.code == 1
    assert "key" in capsys.readouterr().err

    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"k1": _raw_hex(key)}))
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agent-ref",
                "acme/bot@1.0.0",
                "--registry",
                str(tmp_path / "registry"),
            ]
        )

    assert exc.value.code == 1
    assert "artifact" in capsys.readouterr().err


@needs_crypto
def test_cli_refuses_sandboxed_record_without_a_backend(tmp_path, monkeypatch, capsys):
    key = _key()
    _published(tmp_path, key)
    manifest = AgentManifest(
        id="bot",
        version="2.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="sandboxed",
    )
    asyncio.run(FileAgentRegistry(tmp_path / "registry").publish(published_from(manifest)))
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"k1": _raw_hex(key)}))

    with pytest.raises(SystemExit) as exc:
        cli.main(["console", *_common_args(tmp_path, key, "acme/bot@2.0.0")])

    assert exc.value.code == 1
    assert "sandbox" in capsys.readouterr().err


class _SandboxBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, artifact, data, input_text, *, manifest=None):
        from adk_agent.sandbox.agent import SandboxResult

        self.calls.append(input_text)
        return SandboxResult(text="sandboxed")


class _ExplodingLoader:
    async def load(self, artifact, store):
        raise AssertionError("in-process loader used for a sandboxed record")


@needs_crypto
def test_load_agent_returns_sandbox_proxy(tmp_path):
    from adk_agent.sandbox.agent import set_agent_sandbox_backend

    key = _key()
    store, registry = _published(tmp_path, key, execution_tier="sandboxed")
    set_agent_sandbox_backend(_SandboxBackend())
    try:
        agents = asyncio.run(
            load_registry_agents(
                ["acme/bot@1.0.0"],
                registry=registry,
                store=store,
                trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}),
                loader=_ExplodingLoader(),
            )
        )
    finally:
        set_agent_sandbox_backend(None)

    assert type(agents["bot"]).__name__ == "SandboxAgent"
    assert agents["bot"].name == "bot"


@needs_crypto
def test_sandboxed_with_tool_grants_is_refused(tmp_path):
    from adk_agent.sandbox.agent import SandboxToolsUnavailable, set_agent_sandbox_backend

    key = _key()
    store, registry = _published(
        tmp_path,
        key,
        execution_tier="sandboxed",
        tool_grants=[{"tool_id": "crm.read", "data_classes": ["internal"]}],
    )
    set_agent_sandbox_backend(_SandboxBackend())
    try:
        with pytest.raises(SandboxToolsUnavailable):
            asyncio.run(
                load_registry_agents(
                    ["acme/bot@1.0.0"],
                    registry=registry,
                    store=store,
                    trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}),
                    loader=_ExplodingLoader(),
                )
            )
    finally:
        set_agent_sandbox_backend(None)


@needs_crypto
def test_cli_refuses_sandboxed_record_with_tool_grants(tmp_path, monkeypatch, capsys):
    from adk_agent.sandbox.agent import set_agent_sandbox_backend

    key = _key()
    _published(tmp_path, key)
    manifest = AgentManifest(
        id="bot",
        version="3.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="sandboxed",
        tool_grants=[{"tool_id": "crm.read", "data_classes": ["internal"]}],
    )
    digest = "sha256:" + "a" * 64
    artifact = AgentArtifact(digest=digest, size=1, signature=sign_digest(digest, key), key_id="k1")
    asyncio.run(
        FileAgentRegistry(tmp_path / "registry").publish(
            published_from(manifest, artifact=artifact)
        )
    )
    monkeypatch.setenv("ADK_ARTIFACT_KEYS", json.dumps({"k1": _raw_hex(key)}))
    set_agent_sandbox_backend(_SandboxBackend())
    try:
        with pytest.raises(SystemExit) as exc:
            cli._registry_agents(
                argparse.Namespace(
                    agent_ref=["acme/bot@3.0.0"],
                    registry=str(tmp_path / "registry"),
                    artifact_dir=str(tmp_path / "store"),
                    artifact_keys=None,
                    registry_url=None,
                    registry_token_env="ADK_REGISTRY_AUTH_TOKEN",
                )
            )
    finally:
        set_agent_sandbox_backend(None)

    assert exc.value.code == 1
    assert "tool grants" in capsys.readouterr().err


class _ToolBackend(_SandboxBackend):
    supports_tools = True

    async def run(self, artifact, data, input_text, *, manifest=None):
        return await super().run(artifact, data, input_text)


@needs_crypto
def test_loader_allows_tool_grants_with_executor(tmp_path):
    from adk_agent.sandbox.agent import set_agent_sandbox_backend

    key = _key()
    store, registry = _published(
        tmp_path,
        key,
        execution_tier="sandboxed",
        tool_grants=[{"tool_id": "crm.read", "data_classes": ["internal"]}],
    )
    set_agent_sandbox_backend(_ToolBackend())
    try:
        agents = asyncio.run(
            load_registry_agents(
                ["acme/bot@1.0.0"],
                registry=registry,
                store=store,
                trust=TrustStore({"k1": bytes.fromhex(_raw_hex(key))}),
                loader=_ExplodingLoader(),
            )
        )
    finally:
        set_agent_sandbox_backend(None)

    assert type(agents["bot"]).__name__ == "SandboxAgent"
