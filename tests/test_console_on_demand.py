"""SLICE-073: the marketplace loads a published version on request."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentManifest
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


def _manifest(
    version: str = "1.0.0",
    tenant: str = "acme",
    *,
    execution_tier: str | None = None,
    tool_grants=None,
) -> AgentManifest:
    data = {
        "id": "bot",
        "version": version,
        "tenant": tenant,
        "owner": tenant,
        "description": "support bot",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    if execution_tier is not None:
        data["execution_tier"] = execution_tier
    if tool_grants is not None:
        data["tool_grants"] = tool_grants
    return AgentManifest.model_validate(data)


def _project(tmp_path, version: str = "1.0.0", body: str = "support bot"):
    project = tmp_path / f"project-{version}"
    project.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(version)
    (project / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (project / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        f"agent = LlmAgent(name='bot', model='gemini-2.5-pro', instruction={body!r})\n",
        encoding="utf-8",
    )
    return project


def _publish(
    tmp_path,
    registry,
    key,
    *,
    version="1.0.0",
    artifact=True,
    data=None,
    execution_tier=None,
    tool_grants=None,
):
    manifest = _manifest(version, execution_tier=execution_tier, tool_grants=tool_grants)
    if data is None:
        data = pack_agent(_project(tmp_path, version))
    digest = artifact_digest(data)
    signed = sign_digest(digest, key)
    artifact_meta = None
    if artifact:
        from adk_agent.core import AgentArtifact

        artifact_meta = AgentArtifact(digest=digest, size=len(data), signature=signed, key_id="k1")
        asyncio.run(FileArtifactStore(tmp_path / "store").put(artifact_meta, data))
    record = published_from(manifest, artifact=artifact_meta)
    asyncio.run(registry.publish(record))
    return record


def _app(
    tmp_path,
    *,
    agents=None,
    max_loaded_agents: int = 20,
    trust_key=None,
    store: bool = True,
    audit=None,
    roles=None,
):
    key = trust_key if trust_key is not None else _key()
    trust = TrustStore({"k1": _raw(key)}) if trust_key is not False else None
    return build_console_app(
        agents or {},
        auth_token="secret",
        roles=roles,
        registry=FileAgentRegistry(tmp_path / "registry"),
        artifact_store=FileArtifactStore(tmp_path / "store") if store else None,
        artifact_loader=InProcessArtifactLoader(),
        artifact_trust=trust,
        max_loaded_agents=max_loaded_agents,
        audit_sink=audit,
    )


def _load(client, *, version="1.0.0", tenant="acme"):
    return client.post(
        "/api/registry/load",
        json={"tenant": tenant, "id": "bot", "version": version},
        headers=AUTH,
    )


@needs_crypto
def test_load_adds_agent(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    with TestClient(_app(tmp_path, trust_key=key)) as client:
        response = _load(client)
        agents = client.get("/api/agents", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"name": "bot", "version": "1.0.0", "loaded": True}
    assert [item["name"] for item in agents.json()] == ["bot"]


@needs_crypto
def test_loaded_agent_has_runtime(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    with TestClient(_app(tmp_path, trust_key=key)) as client:
        _load(client)
        sessions = client.get("/api/sessions?agent=bot", headers=AUTH)

    assert sessions.status_code == 200
    assert sessions.json() == []


@needs_crypto
def test_already_loaded_returns_false(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    loaded = LlmAgent(name="bot", model="gemini-2.5-pro", instruction="x")
    with TestClient(_app(tmp_path, agents={"bot": loaded}, trust_key=key)) as client:
        response = _load(client)

    assert response.status_code == 200
    assert response.json() == {"name": "bot", "version": "1.0.0", "loaded": False}


@needs_crypto
def test_missing_version(tmp_path):
    key = _key()
    with TestClient(_app(tmp_path, trust_key=key)) as client:
        response = _load(client, version="9.9.9")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


@needs_crypto
def test_missing_artifact(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key, artifact=False)
    with TestClient(_app(tmp_path, trust_key=key)) as client:
        response = _load(client)

    assert response.status_code == 409
    assert response.json() == {"error": "artifact_missing"}


@needs_crypto
def test_untrusted_artifact(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    with TestClient(_app(tmp_path, trust_key=_key())) as client:
        response = _load(client)

    assert response.status_code == 409
    assert response.json() == {"error": "artifact_untrusted"}


@needs_crypto
def test_cross_tenant_forbidden(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    with TestClient(_app(tmp_path, trust_key=key, roles=["publisher"])) as client:
        response = _load(client, tenant="acme")

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


@needs_crypto
def test_load_limit(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    probe = LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")
    with TestClient(
        _app(tmp_path, agents={"probe": probe}, trust_key=key, max_loaded_agents=1)
    ) as client:
        response = _load(client)

    assert response.status_code == 409
    assert response.json() == {"error": "load_limit"}


@needs_crypto
def test_requires_store_and_trust(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    with TestClient(_app(tmp_path, trust_key=False)) as client:
        no_trust = _load(client)
    with TestClient(_app(tmp_path, trust_key=key, store=False)) as client:
        no_store = _load(client)

    assert no_trust.status_code == 503
    assert no_trust.json() == {"error": "artifact_trust_unavailable"}
    assert no_store.status_code == 503
    assert no_store.json() == {"error": "artifact_store_unavailable"}


@needs_crypto
def test_name_conflict_across_versions(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key, version="1.0.0")
    _publish(tmp_path, registry, key, version="2.0.0")
    with TestClient(_app(tmp_path, trust_key=key)) as client:
        assert _load(client, version="1.0.0").status_code == 200
        response = _load(client, version="2.0.0")

    assert response.status_code == 409
    assert response.json() == {"error": "name_conflict"}


@needs_crypto
def test_load_failure(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key, data=b"not a zip")
    with TestClient(_app(tmp_path, trust_key=key)) as client:
        response = _load(client)

    assert response.status_code == 500
    assert response.json() == {"error": "load_failed"}


@needs_crypto
def test_audit_records_load(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key)
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, trust_key=key, audit=sink)) as client:
        _load(client)

    [event] = [item for item in sink.recent() if item.action == "agent.load"]
    assert event.status == "ok"
    assert event.target == "bot"
    assert event.tenant == "local"


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


def test_cli_wires_store_and_limit(tmp_path, monkeypatch):
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"k1": "00" * 32}), encoding="utf-8")
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(
        [
            "console",
            "--agents",
            _agents_file(tmp_path),
            "--artifact-dir",
            str(tmp_path / "store"),
            "--artifact-keys",
            str(keys),
            "--max-loaded-agents",
            "5",
        ]
    )

    assert captured["artifact_store"] is not None
    assert captured["artifact_loader"] is not None
    assert captured["max_loaded_agents"] == 5


@needs_crypto
def test_sandboxed_record_is_refused(tmp_path):
    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    sandboxed = published_from(
        _manifest(version="2.0.0").model_copy(update={"execution_tier": "sandboxed"})
    )
    asyncio.run(registry.publish(sandboxed))

    with TestClient(_app(tmp_path, trust_key=key)) as client:
        response = _load(client, version="2.0.0")

    assert response.status_code == 409
    assert response.json() == {"error": "sandbox_unavailable"}


class _SandboxBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, artifact, data, input_text, *, manifest=None, invocation=None):
        from adk_agent.sandbox.agent import SandboxResult

        self.calls.append(input_text)
        return SandboxResult(text="answer from sandbox")


@needs_crypto
def test_on_demand_sandboxed_uses_proxy(tmp_path):
    from adk_agent.sandbox.agent import set_agent_sandbox_backend

    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(tmp_path, registry, key, execution_tier="sandboxed")
    backend = _SandboxBackend()
    set_agent_sandbox_backend(backend)
    try:
        with TestClient(_app(tmp_path, trust_key=key)) as client:
            loaded = _load(client)
            assert loaded.status_code == 200
            chat = client.post(
                "/api/chat",
                json={"agent": "bot", "message": "hello"},
                headers=AUTH,
            )
    finally:
        set_agent_sandbox_backend(None)

    assert chat.status_code == 200
    assert backend.calls == ["hello"]


@needs_crypto
def test_on_demand_sandboxed_tool_grants_refused(tmp_path):
    from adk_agent.sandbox.agent import set_agent_sandbox_backend

    key = _key()
    registry = FileAgentRegistry(tmp_path / "registry")
    _publish(
        tmp_path,
        registry,
        key,
        execution_tier="sandboxed",
        tool_grants=[{"tool_id": "crm.read", "data_classes": ["internal"]}],
    )
    set_agent_sandbox_backend(_SandboxBackend())
    try:
        with TestClient(_app(tmp_path, trust_key=key)) as client:
            loaded = _load(client)
    finally:
        set_agent_sandbox_backend(None)

    assert loaded.status_code == 409
    assert loaded.json() == {"error": "tool_mediation_unavailable"}
