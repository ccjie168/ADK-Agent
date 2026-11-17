"""SLICE-029: console policy endpoints and the RBAC check on chat."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _policy(version: str = "1") -> dict:
    return {
        "version": version,
        "bindings": [
            {
                "role": "ops",
                "tenant": "local",
                "allow": ["agent.run:*", "policy.update:*"],
            }
        ],
    }


def _write_policy(path: Path, policy: dict) -> Path:
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def _client(
    tmp_path: Path,
    *,
    roles=("ops",),
    policy: dict | None = None,
    audit=None,
) -> TestClient:
    policy_file = _write_policy(tmp_path / "policy.json", policy or _policy())
    app = build_console_app(
        _agents(),
        auth_token="secret",
        policy_file=str(policy_file),
        roles=list(roles),
        audit_sink=audit,
    )
    return TestClient(app)


def test_get_policy(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/policy", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["version"] == "1"


def test_put_policy_persists_and_audits(tmp_path):
    policy_file = tmp_path / "policy.json"
    with _client(tmp_path) as client:
        response = client.put("/api/policy", json=_policy("2"), headers=AUTH)
        assert response.status_code == 200
        assert response.json()["version"] == "2"

        audit = client.get("/api/audit?limit=20", headers=AUTH).json()

    assert json.loads(policy_file.read_text())["version"] == "2"
    updates = [event for event in audit if event["action"] == "policy.update"]
    assert len(updates) == 1
    assert updates[0]["target"] == "2"
    assert updates[0]["status"] == "ok"


def test_put_policy_denied_without_role(tmp_path):
    policy_file = tmp_path / "policy.json"
    sink = ListAuditSink()
    with _client(tmp_path, roles=("guest",), audit=sink) as client:
        response = client.put("/api/policy", json=_policy("2"), headers=AUTH)
        assert response.status_code == 403

    assert json.loads(policy_file.read_text())["version"] == "1"
    [event] = [item for item in sink.recent() if item.action == "policy.update"]
    assert event.status == "denied"
    assert event.error_code == "policy_denied"
    with _client(tmp_path) as client:
        current = client.get("/api/policy", headers=AUTH).json()

    assert current["version"] == "1"


def test_put_invalid_policy_keeps_old(tmp_path):
    policy_file = tmp_path / "policy.json"
    with _client(tmp_path) as client:
        response = client.put("/api/policy", json={"version": ""}, headers=AUTH)
        assert response.status_code == 400
        current = client.get("/api/policy", headers=AUTH).json()

    assert current["version"] == "1"
    assert json.loads(policy_file.read_text())["version"] == "1"


def test_policy_endpoints_absent_without_policy_file():
    app = build_console_app(_agents(), auth_token="secret")
    with TestClient(app) as client:
        assert client.get("/api/policy", headers=AUTH).status_code == 404
        assert client.put("/api/policy", json=_policy("2"), headers=AUTH).status_code == 404


def test_chat_denied_without_role(tmp_path, monkeypatch):
    calls = 0

    async def counted_run(self, **kwargs):
        nonlocal calls
        calls += 1
        for _ in ():
            yield

    monkeypatch.setattr("google.adk.runners.Runner.run_async", counted_run)
    sink = ListAuditSink()
    with _client(tmp_path, roles=("guest",), audit=sink) as client:
        response = client.post("/api/chat", json={"agent": "probe", "message": "hi"}, headers=AUTH)

    assert response.status_code == 403
    assert calls == 0
    [event] = [item for item in sink.recent() if item.action == "agent.run"]
    assert event.status == "denied"
    assert event.error_code == "policy_denied"


def test_get_policy_requires_capability(tmp_path):
    with _client(tmp_path, roles=("guest",)) as client:
        response = client.get("/api/policy", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_chat_allowed_with_role(tmp_path, monkeypatch):
    async def empty_run(self, **kwargs):
        for _ in ():
            yield

    monkeypatch.setattr("google.adk.runners.Runner.run_async", empty_run)
    with _client(tmp_path, roles=("ops",)) as client:
        response = client.post("/api/chat", json={"agent": "probe", "message": "hi"}, headers=AUTH)
    assert response.status_code == 200


def test_index_has_policy_panel(tmp_path):
    with _client(tmp_path) as client:
        page = client.get("/")
    assert "Policies" in page.text
    assert "/api/policy" in page.text
