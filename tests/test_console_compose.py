"""SLICE-280: the console previews and publishes composed agents (ADR-0043)."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.compose import build_composed
from adk_agent.console import build_console_app
from adk_agent.registry import FileAgentRegistry, FileArtifactStore
from adk_agent.registry.artifacts import artifact_digest
from adk_agent.registry.signing import verify_digest

AUTH = {"Authorization": "Bearer secret"}
BODY = {
    "template_id": "single-llm",
    "name": "support_bot",
    "version": "1.0.0",
    "tenant": "local",
    "instruction": "You are helpful.",
    "tools": ["ping"],
    "data_classes": ["internal"],
}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _key():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    return key, key.public_key()


def _app(
    tmp_path,
    *,
    roles=("publisher",),
    registry=True,
    store=True,
    keys=False,
    audit_sink=None,
):
    kwargs = {}
    public_key = None
    if registry:
        kwargs["registry"] = FileAgentRegistry(tmp_path / "registry")
    if store:
        kwargs["artifact_store"] = FileArtifactStore(tmp_path / "artifacts")
    if keys:
        key, public_key = _key()
        kwargs.update(
            compose_key=key,
            compose_key_id="compose-1",
            compose_builder_key=key,
            compose_builder_key_id="builder-1",
        )
    if audit_sink is not None:
        kwargs["audit_sink"] = audit_sink
    return build_console_app(
        _agents(), auth_token="secret", roles=list(roles), **kwargs
    ), public_key


def test_compose_templates_require_publish_capability(tmp_path):
    app, _ = _app(tmp_path, roles=("operator",), store=False)
    with TestClient(app) as client:
        denied = client.get("/api/compose/templates", headers=AUTH)
    assert denied.status_code == 403
    assert denied.json() == {"error": "forbidden"}

    app, _ = _app(tmp_path, roles=("publisher",), store=False)
    with TestClient(app) as client:
        granted = client.get("/api/compose/templates", headers=AUTH)
    assert granted.status_code == 200
    body = granted.json()
    assert body["configured"] is False
    assert body["templates"][0]["template_id"] == "single-llm"


def test_compose_preview_renders_the_bundle(tmp_path):
    app, _ = _app(tmp_path, store=False)
    with TestClient(app) as client:
        response = client.post("/api/compose/preview", json=BODY, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    manifest, data = build_composed(**BODY)
    assert body["manifest"]["id"] == "support_bot"
    assert body["manifest"]["tenant"] == "local"
    assert body["manifest"]["data_scopes"] == ["internal"]
    assert body["agent_py"].endswith("root_agent = agent\n")
    assert "'You are helpful.'" in body["agent_py"]
    assert body["artifact_digest"] == artifact_digest(data)
    assert body["size"] == len(data)


def test_compose_preview_rejects_bad_parameters(tmp_path):
    app, _ = _app(tmp_path, store=False)
    cases = [
        {**BODY, "template_id": "multi-llm"},
        {**BODY, "name": "1bad"},
        {**BODY, "instruction": ""},
        {**BODY, "instruction": "x" * 4001},
        {**BODY, "tools": 5},
        {**BODY, "tools": ["shell"]},
        {**BODY, "data_classes": ["secret"]},
    ]
    with TestClient(app) as client:
        for case in cases:
            response = client.post("/api/compose/preview", json=case, headers=AUTH)
            assert response.status_code == 400, case
            assert response.json() == {"error": "compose_invalid"}
        not_json = client.post(
            "/api/compose/preview",
            content=b"not json",
            headers={**AUTH, "Content-Type": "application/json"},
        )
    assert not_json.status_code == 400
    assert not_json.json() == {"error": "compose_invalid"}


def test_compose_preview_forbids_a_foreign_tenant(tmp_path):
    app, _ = _app(tmp_path, store=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/compose/preview", json={**BODY, "tenant": "team-a"}, headers=AUTH
        )
    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


def test_compose_preview_works_without_signing_keys(tmp_path):
    app, _ = _app(tmp_path, keys=False, store=False)
    with TestClient(app) as client:
        templates = client.get("/api/compose/templates", headers=AUTH)
        preview = client.post("/api/compose/preview", json=BODY, headers=AUTH)
    assert templates.json()["configured"] is False
    assert preview.status_code == 200
    assert preview.json()["artifact_digest"].startswith("sha256:")


def test_compose_publish_requires_compose_capability(tmp_path):
    app, _ = _app(tmp_path, roles=("operator",), keys=True)
    with TestClient(app) as client:
        response = client.post("/api/compose", json=BODY, headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}
    assert asyncio.run(FileAgentRegistry(tmp_path / "registry").list("local")) == []


def test_compose_publish_returns_compose_not_configured(tmp_path):
    app, _ = _app(tmp_path, keys=False)
    with TestClient(app) as client:
        response = client.post("/api/compose", json=BODY, headers=AUTH)
    assert response.status_code == 404
    assert response.json() == {"error": "compose_not_configured"}


def test_compose_requires_a_registry(tmp_path):
    app, _ = _app(tmp_path, registry=False, keys=True)
    with TestClient(app) as client:
        response = client.post("/api/compose", json=BODY, headers=AUTH)
    assert response.status_code == 404
    assert response.json() == {"error": "registry_not_configured"}


def test_compose_publish_stores_a_signed_artifact(tmp_path):
    app, public_key = _app(tmp_path, roles=("admin",), keys=True)
    with TestClient(app) as client:
        response = client.post("/api/compose", json=BODY, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["tenant"] == "local"
    assert body["id"] == "support_bot"
    assert body["version"] == "1.0.0"

    registry = FileAgentRegistry(tmp_path / "registry")
    records = asyncio.run(registry.list("local"))
    assert len(records) == 1
    record = records[0]
    assert record.digest == body["digest"]
    assert record.artifact is not None
    assert record.artifact.digest == body["artifact_digest"]
    assert record.artifact.key_id == "compose-1"
    assert record.artifact.builder_key_id == "builder-1"
    assert verify_digest(record.artifact.digest, record.artifact.signature, public_key)
    assert record.artifact.builder_signature is not None
    assert verify_digest(record.artifact.digest, record.artifact.builder_signature, public_key)

    store = FileArtifactStore(tmp_path / "artifacts")
    stored = asyncio.run(store.get(body["artifact_digest"]))
    assert stored is not None
    assert artifact_digest(stored) == body["artifact_digest"]


def test_compose_audit_omits_the_instruction(tmp_path):
    sink = ListAuditSink()
    app, _ = _app(tmp_path, keys=True, audit_sink=sink)
    with TestClient(app) as client:
        response = client.post("/api/compose", json=BODY, headers=AUTH)
    assert response.status_code == 200
    events = [event for event in sink.recent() if event.action == "agent.compose"]
    assert len(events) == 1
    event = events[0]
    assert event.template_id == "single-llm"
    assert event.target == "support_bot"
    assert event.agent_ref.id == "support_bot"
    assert event.agent_ref.artifact_digest == response.json()["artifact_digest"]
    assert "You are helpful." not in json.dumps(event.model_dump(mode="json"))


def test_compose_publish_rejects_a_foreign_tenant(tmp_path):
    app, _ = _app(tmp_path, keys=True)
    with TestClient(app) as client:
        response = client.post("/api/compose", json={**BODY, "tenant": "team-a"}, headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}
    assert asyncio.run(FileAgentRegistry(tmp_path / "registry").list("team-a")) == []


def test_compose_capability_reaches_publisher(tmp_path):
    app, _ = _app(tmp_path, store=False)
    with TestClient(app) as client:
        publisher = set(client.get("/api/me", headers=AUTH).json()["capabilities"])
    assert "registry.compose" in publisher

    app, _ = _app(tmp_path, roles=("admin",), store=False)
    with TestClient(app) as client:
        admin = set(client.get("/api/me", headers=AUTH).json()["capabilities"])
    assert "registry.compose" in admin

    app, _ = _app(tmp_path, roles=("operator",), store=False)
    with TestClient(app) as client:
        operator = set(client.get("/api/me", headers=AUTH).json()["capabilities"])
    assert "registry.compose" not in operator
