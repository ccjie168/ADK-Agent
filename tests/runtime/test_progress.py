"""SLICE-036: the runtime emits structured progress events."""

from __future__ import annotations

import asyncio
from typing import Any

from adk_agent.core import AgentRef, Invocation, Principal, ProgressEvent
from adk_agent.runtime import AgentRuntime


class FakeCall:
    def __init__(self, name: str, args: dict | None = None) -> None:
        self.name = name
        self.args = args or {}


class FakeResponse:
    def __init__(self, name: str, response: dict | None = None) -> None:
        self.name = name
        self.response = response or {}


class FakePart:
    def __init__(
        self,
        text: str | None = None,
        thought: bool = False,
        function_call: FakeCall | None = None,
        function_response: FakeResponse | None = None,
    ) -> None:
        self.text = text
        self.thought = thought
        self.function_call = function_call
        self.function_response = function_response


class FakeContent:
    def __init__(self, parts: list[FakePart]) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, parts: list[FakePart], author: str = "bot", final: bool = False) -> None:
        self.author = author
        self.content = FakeContent(parts)
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class FakeRunner:
    def __init__(self, events=None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error

    async def run_async(self, **kwargs):
        if self.error:
            raise self.error
        for event in self.events:
            yield event


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _run(runner: FakeRunner, sink: list[ProgressEvent], audit: FakeAudit | None = None):
    async def on_progress(event: ProgressEvent) -> None:
        sink.append(event)

    return asyncio.run(
        AgentRuntime(runner, audit=audit).run(
            _invocation(), user_id="u1", session_id="s1", on_progress=on_progress
        )
    )


def test_progress_sequence():
    runner = FakeRunner([FakeEvent([FakePart("hello")], final=True)])
    events: list[ProgressEvent] = []

    result = _run(runner, events)

    assert result.text == "hello"
    assert events[0].kind == "run.started"
    assert events[-1].kind == "run.finished"
    assert events[-1].text == "hello"
    assert all(event.run_id == "r1" and event.trace_id == "tr1" for event in events)


def test_progress_reports_tools():
    runner = FakeRunner(
        [
            FakeEvent([FakePart(function_call=FakeCall("get_time"))]),
            FakeEvent([FakePart(function_response=FakeResponse("get_time"))]),
            FakeEvent([FakePart("done")], final=True),
        ]
    )
    events: list[ProgressEvent] = []

    _run(runner, events)

    kinds = [event.kind for event in events]
    assert kinds == ["run.started", "tool.call", "tool.result", "model.text", "run.finished"]
    assert events[1].tool == "get_time"
    assert events[2].tool == "get_time"


def test_progress_callback_failure_is_ignored():
    runner = FakeRunner([FakeEvent([FakePart("hello")], final=True)])
    audit = FakeAudit()

    async def broken(event: ProgressEvent) -> None:
        raise RuntimeError("ui went away")

    result = asyncio.run(
        AgentRuntime(runner, audit=audit).run(
            _invocation(), user_id="u1", session_id="s1", on_progress=broken
        )
    )

    assert result.text == "hello"
    assert audit.events[-1].status == "ok"


def test_progress_reports_failure():
    runner = FakeRunner(error=RuntimeError("boom"))
    events: list[ProgressEvent] = []

    try:
        _run(runner, events)
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("run should raise")

    assert events[-1].kind == "run.failed"
    assert events[-1].detail == "RuntimeError"
