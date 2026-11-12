"""SLICE-038: the console lists sessions without leaking state or events."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

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


def _session_service():
    service = InMemorySessionService()
    session = asyncio.run(service.create_session(app_name="probe", user_id="console_user"))
    return service, session


def test_sessions_omit_state_and_events():
    service, session = _session_service()
    app = build_console_app(_agents(), auth_token="secret", session_service=service)

    with TestClient(app) as client:
        response = client.get("/api/sessions?agent=probe", headers=AUTH)

    assert response.status_code == 200
    [summary] = response.json()
    assert set(summary) == {"session_id", "last_update_time"}
    assert summary["session_id"] == session.id
    assert "state" not in summary
    assert "events" not in summary


def test_sessions_reject_unknown_agent():
    service, _ = _session_service()
    app = build_console_app(_agents(), auth_token="secret", session_service=service)

    with TestClient(app) as client:
        response = client.get("/api/sessions?agent=nope", headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "unknown_agent"}
