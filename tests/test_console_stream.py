"""SLICE-036: the console streams run progress over SSE."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


class FakeCall:
    def __init__(self, name: str) -> None:
        self.name = name
        self.args = {}


class FakePart:
    def __init__(self, text: str | None = None, function_call: FakeCall | None = None) -> None:
        self.text = text
        self.thought = False
        self.function_call = function_call
        self.function_response = None


class FakeContent:
    def __init__(self, parts: list[FakePart]) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, parts: list[FakePart], final: bool = False) -> None:
        self.author = "probe"
        self.content = FakeContent(parts)
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


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
        yield FakeEvent([FakePart(function_call=FakeCall("get_time"))])
        yield FakeEvent([FakePart("hi there")], final=True)

    monkeypatch.setattr("google.adk.runners.Runner.run_async", run_async)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name:
            events.append((name, json.loads(data)))
    return events


def test_stream_emits_progress_and_done(monkeypatch):
    _patch_runner(monkeypatch)
    with (
        TestClient(build_console_app(_agents(), auth_token="secret")) as client,
        client.stream(
            "POST",
            "/api/chat/stream",
            json={"agent": "probe", "message": "hi"},
            headers=AUTH,
        ) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse("".join(response.iter_text()))

    names = [name for name, _ in events]
    assert names[0] == "progress"
    assert names[-1] == "done"
    kinds = [payload["kind"] for name, payload in events if name == "progress"]
    assert kinds[0] == "run.started"
    assert "tool.call" in kinds
    assert kinds[-1] == "run.finished"
    done = events[-1][1]
    assert done["reply"] == "hi there"
    assert done["trace_id"]


def test_stream_requires_token():
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        response = client.post("/api/chat/stream", json={"agent": "probe", "message": "hi"})
    assert response.status_code == 401


def test_stream_denied_by_policy(tmp_path, monkeypatch):
    _patch_runner(monkeypatch)
    policy = {
        "version": "1",
        "bindings": [
            {"role": "ops", "tenant": "local", "allow": ["agent.run:*", "policy.update:*"]}
        ],
    }
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    app = build_console_app(
        _agents(), auth_token="secret", policy_file=str(policy_file), roles=["guest"]
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream", json={"agent": "probe", "message": "hi"}, headers=AUTH
        )
    assert response.status_code == 403
    assert response.json() == {"error": "policy_denied"}


def test_index_has_progress_panels():
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        page = client.get("/")
    assert "Run progress" in page.text
    assert "/api/chat/stream" in page.text
    assert "/api/traces/" in page.text
