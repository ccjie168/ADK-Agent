"""SLICE-016: the console exposes run-level audit."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


def _agents():
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def test_chat_writes_audit_event(monkeypatch):
    async def empty_run(self, **kwargs):
        for _ in ():
            yield

    monkeypatch.setattr("google.adk.runners.Runner.run_async", empty_run)
    with TestClient(build_console_app(_agents(), auth_token="secret", roles=["admin"])) as client:
        chat = client.post(
            "/api/chat",
            json={"agent": "probe", "message": "hi"},
            headers={**AUTH, "X-Trace-Id": "trace-123"},
        )
        assert chat.status_code == 200
        audit = client.get("/api/audit?limit=10", headers=AUTH)

    assert audit.status_code == 200
    [event] = audit.json()
    assert event["action"] == "agent.run"
    assert event["run_id"] == chat.json()["run_id"]
    assert event["trace_id"] == "trace-123"
    assert event["status"] == "ok"


def test_audit_requires_token():
    with TestClient(build_console_app(_agents(), auth_token="secret", roles=["admin"])) as client:
        assert client.get("/api/audit").status_code == 401


def test_read_requires_capability():
    with TestClient(build_console_app(_agents(), auth_token="secret", roles=["viewer"])) as client:
        response = client.get("/api/audit", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_operator_can_read_audit():
    with TestClient(
        build_console_app(_agents(), auth_token="secret", roles=["operator"])
    ) as client:
        response = client.get("/api/audit", headers=AUTH)

    assert response.status_code == 200
