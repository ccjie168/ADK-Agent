"""SLICE-235: operational read panels require ops.read / model.read."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


def _app(roles: list[str]):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
    )


def test_ops_read_panels_require_ops_read():
    with TestClient(_app(["requester"])) as client:
        for path in ("/api/overview", "/api/quota", "/api/rag", "/api/semantics"):
            response = client.get(path, headers=AUTH)
            assert response.status_code == 403, f"{path} -> {response.status_code}"
            assert response.json() == {"error": "forbidden"}


def test_model_panel_requires_model_read():
    with TestClient(_app(["requester"])) as client:
        response = client.get("/api/model", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}
