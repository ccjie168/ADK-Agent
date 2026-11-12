"""SLICE-047: the console accepts W3C traceparent on chat."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}
TRACE = "4bf9" * 8
PARENT = "00f0" * 4
TRACEPARENT = f"00-{TRACE}-{PARENT}-01"


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


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _patch_runner(monkeypatch) -> None:
    async def run_async(self, **kwargs):
        yield FakeEvent("hi there")

    monkeypatch.setattr("google.adk.runners.Runner.run_async", run_async)


def _chat(monkeypatch, headers: dict[str, str]) -> dict:
    _patch_runner(monkeypatch)
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        response = client.post(
            "/api/chat",
            json={"agent": "probe", "message": "hi"},
            headers={**AUTH, **headers},
        )

    assert response.status_code == 200
    return response.json()


def test_traceparent_used(monkeypatch):
    body = _chat(monkeypatch, {"traceparent": TRACEPARENT})

    assert body["trace_id"] == TRACE


def test_x_trace_id_wins(monkeypatch):
    body = _chat(monkeypatch, {"traceparent": TRACEPARENT, "X-Trace-Id": "console-trace"})

    assert body["trace_id"] == "console-trace"


def test_malformed_traceparent_generates(monkeypatch):
    body = _chat(monkeypatch, {"traceparent": "not-a-traceparent"})

    assert body["trace_id"] != "not-a-traceparent"
    assert re.fullmatch(r"[0-9a-f]{32}", body["trace_id"])
