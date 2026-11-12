"""SLICE-036: the console exposes a trace view for one run."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import _trace_payload, build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

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


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False
        self.function_call = None
        self.function_response = None


class FakeContent:
    def __init__(self, parts: list[FakePart]) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, text: str) -> None:
        self.author = "probe"
        self.content = FakeContent([FakePart(text)])

    def is_final_response(self) -> bool:
        return True


def _event(action: str, target: str, *, trace_id: str = "trace-1", status="ok") -> AuditEvent:
    return AuditEvent(
        event_id=f"{action}-{target}",
        run_id="r1",
        trace_id=trace_id,
        tenant="local",
        principal=Principal(tenant="local", subject="console_user", kind="human"),
        agent_ref=AgentRef(id="probe", version="dev", digest="d" * 64),
        action=action,
        target=target,
        status=status,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_trace_payload_has_root_and_children():
    events = [
        _event("model.call", "litellm:deepseek"),
        _event("tool.call", "get_time"),
        _event("agent.run", "probe@dev"),
    ]

    payload = _trace_payload(events, "trace-1")

    assert payload["error"] is None
    root = payload["root"]
    assert root["kind"] == "agent"
    assert root["status"] == "ok"
    assert [child["kind"] for child in root["children"]] == ["model", "tool"]


def test_trace_after_chat(monkeypatch):
    async def run_async(self, **kwargs):
        yield FakeEvent("hi there")

    monkeypatch.setattr("google.adk.runners.Runner.run_async", run_async)
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        chat = client.post(
            "/api/chat",
            json={"agent": "probe", "message": "hi"},
            headers={**AUTH, "X-Trace-Id": "trace-123"},
        )
        response = client.get(f"/api/traces/{chat.json()['trace_id']}", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == "trace-123"
    assert payload["root"]["id"] == "probe@dev"
    assert payload["root"]["children"] == []


def test_unknown_trace():
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        response = client.get("/api/traces/does-not-exist", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "trace_id": "does-not-exist",
        "root": None,
        "error": "trace_not_found",
    }


def test_trace_requires_token():
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        assert client.get("/api/traces/x").status_code == 401
