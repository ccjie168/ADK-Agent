"""SLICE-004: private web console (auth + agent list)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _client(token: str = "secret") -> TestClient:
    app = build_console_app(_agents(), auth_token=token)
    return TestClient(app)


def test_healthz_and_index_open():
    with _client() as client:
        assert client.get("/healthz").status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "ADK Console" in page.text


def test_api_requires_token():
    with _client() as client:
        assert client.get("/api/agents").status_code == 401
        assert client.post("/api/chat", json={}).status_code == 401


def test_agents_with_token():
    with _client() as client:
        response = client.get("/api/agents", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    assert response.json() == [{"name": "probe", "description": "probe agent"}]


def test_chat_validates_input():
    headers = {"Authorization": "Bearer secret"}
    with _client() as client:
        assert client.post("/api/chat", json={}, headers=headers).status_code == 400
        unknown = client.post("/api/chat", json={"agent": "nope", "message": "hi"}, headers=headers)
        assert unknown.status_code == 400
        empty = client.post("/api/chat", json={"agent": "probe", "message": " "}, headers=headers)
        assert empty.status_code == 400


def test_index_has_management_panels():
    with _client() as client:
        page = client.get("/")

    for element in (
        "tabs",
        "tab-chat",
        "tab-registry",
        "tab-runs",
        "tab-sessions",
        "tab-policy",
        "tab-approvals",
        "tab-plans",
        "registry",
        "runs",
        "sessions",
        "approvals-body",
        "plans-body",
    ):
        assert f'id="{element}"' in page.text
    assert "Registry" in page.text
    assert "Runs" in page.text
    assert "Approvals" in page.text
    assert "Plans" in page.text


def test_audit_block_is_capability_gated():
    with _client() as client:
        page = client.get("/")

    assert 'data-capability="audit.read"' in page.text
