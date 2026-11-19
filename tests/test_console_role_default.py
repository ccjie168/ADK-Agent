"""SLICE-163: console principal defaults to requester, not admin."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

BASE = {"chat.run", "runs.read", "sessions.read"}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _me() -> dict:
    app = build_console_app(_agents(), auth_token="secret")
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    return response.json()


def test_default_role_is_requester():
    body = _me()
    assert body["roles"] == ["requester"]
    assert set(body["capabilities"]) == BASE


def test_default_role_is_not_admin():
    body = _me()
    assert "admin" not in body["roles"]
    assert "registry.load" not in set(body["capabilities"])
