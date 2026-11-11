"""SLICE-010: console session recovery and error visibility."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


def _app():
    agents = {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }
    return build_console_app(agents, auth_token="secret")


def test_stale_session_is_replaced(monkeypatch):
    async def empty_run(self, **kwargs):
        for _ in ():
            yield

    monkeypatch.setattr("google.adk.runners.Runner.run_async", empty_run)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/chat",
            json={"agent": "probe", "message": "hi", "session_id": "missing"},
            headers=AUTH,
        )
    assert response.status_code == 200
    assert response.json()["session_id"] != "missing"


def test_chat_returns_trace_ids(monkeypatch):
    async def empty_run(self, **kwargs):
        for _ in ():
            yield

    monkeypatch.setattr("google.adk.runners.Runner.run_async", empty_run)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/chat",
            json={"agent": "probe", "message": "hi"},
            headers={**AUTH, "X-Trace-Id": "trace-123"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == "trace-123"
    assert body["run_id"]


def test_chat_failure_is_logged(monkeypatch, caplog):
    async def boom(self, **kwargs):
        raise RuntimeError("model exploded")
        yield  # pragma: no cover

    monkeypatch.setattr("google.adk.runners.Runner.run_async", boom)
    with TestClient(_app()) as client, caplog.at_level(logging.ERROR, logger="adk_agent.console"):
        response = client.post(
            "/api/chat",
            json={"agent": "probe", "message": "hi"},
            headers=AUTH,
        )
    assert response.status_code == 500
    assert "agent run failed" in caplog.text
    assert any(record.exc_info for record in caplog.records)
