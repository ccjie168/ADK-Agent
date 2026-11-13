"""SLICE-057: the SSE progress buffer is bounded and reports drops."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.console import ProgressBuffer, build_console_app

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


def test_buffer_drops_oldest_progress():
    async def scenario():
        buffer = ProgressBuffer(max_progress=2)
        for index in range(4):
            buffer.put_progress({"seq": index})
        await buffer.put_terminal("done", {"reply": "x"})
        return buffer, [await buffer.get() for _ in range(3)]

    buffer, items = asyncio.run(scenario())

    assert buffer.dropped == 2
    assert items[0] == ("progress", {"seq": 2})
    assert items[1] == ("progress", {"seq": 3})
    assert items[2][0] == "done"
    assert items[2][1] == {"reply": "x", "dropped": 2}


def test_terminal_is_never_dropped():
    async def scenario():
        buffer = ProgressBuffer(max_progress=1)
        for index in range(5):
            buffer.put_progress({"seq": index})
        await buffer.put_terminal("error", {"error": "quota_exceeded"})
        return buffer, [await buffer.get() for _ in range(2)]

    buffer, items = asyncio.run(scenario())

    assert items[0] == ("progress", {"seq": 4})
    assert items[1] == ("error", {"error": "quota_exceeded", "dropped": 4})
    assert buffer.dropped == 4


def test_peak_depth_is_bounded():
    buffer = ProgressBuffer(max_progress=5)
    for index in range(100):
        buffer.put_progress({"seq": index})

    assert buffer.peak_depth == 5
    assert buffer.depth == 5
    assert buffer.dropped == 95


def test_buffer_rejects_bad_size():
    with pytest.raises(ValueError):
        ProgressBuffer(max_progress=0)


def test_stream_reports_dropped(monkeypatch):
    _patch_runner(monkeypatch)
    app = build_console_app(_agents(), auth_token="secret", sse_queue_size=3)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream",
            json={"agent": "probe", "message": "hello"},
            headers=AUTH,
        )

    events = _parse_sse(response.text)
    kinds = [name for name, _ in events]
    assert kinds[0] == "progress"
    assert kinds[-1] == "done"
    assert events[-1][1]["reply"] == "hi there"
    assert events[-1][1]["dropped"] == 0


def test_console_rejects_zero_queue(tmp_path, monkeypatch, capsys):
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["console", "--agents", str(path), "--sse-queue-size", "0"])

    assert exc.value.code == 1
    assert "sse-queue-size" in capsys.readouterr().err
