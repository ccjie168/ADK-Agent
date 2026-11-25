"""SLICE-284: publishers can see the platform overview without gaining writes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


def _app(role: str):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=[role],
    )


def test_publisher_capability_set_includes_ops_read():
    with TestClient(_app("publisher")) as client:
        capabilities = set(client.get("/api/me", headers=AUTH).json()["capabilities"])
    assert "ops.read" in capabilities
    assert "registry.compose" in capabilities


def test_publisher_gets_the_overview():
    with TestClient(_app("publisher")) as client:
        response = client.get("/api/overview", headers=AUTH)
    assert response.status_code == 200
    assert [card["key"] for card in response.json()["cards"]] == [
        "approvals",
        "agents",
        "tools",
        "grants",
    ]


def test_base_role_still_lacks_the_overview():
    with TestClient(_app("viewer")) as client:
        response = client.get("/api/overview", headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}
