"""SLICE-233: console capability checks precede config/param errors (no probing)."""

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


def test_unconfigured_read_routes_403_before_404():
    with TestClient(_app(["requester"])) as client:
        for path in (
            "/api/credentials",
            "/api/connector-requests",
            "/api/peers",
            "/api/remote-agents",
        ):
            response = client.get(path, headers=AUTH)
            assert response.status_code == 403, f"{path} -> {response.status_code}"
            assert response.json() == {"error": "forbidden"}


def test_unconfigured_write_routes_403_before_404():
    with TestClient(_app(["requester"])) as client:
        for path in (
            "/api/connectors/missing/check",
            "/api/peers/missing/disable",
            "/api/peers/missing/grants",
            "/api/remote-agents/missing/refresh",
        ):
            response = client.post(path, headers=AUTH, json={})
            assert response.status_code == 403, f"{path} -> {response.status_code}"
            assert response.json() == {"error": "forbidden"}
