"""SLICE-014: the runtime injects trace metadata and audits agent runs."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import AgentRef, Invocation, Principal
from adk_agent.runtime import AgentRuntime


class FakePart:
    def __init__(self, text: str | None = None, thought: bool = False) -> None:
        self.text = text
        self.thought = thought


class FakeContent:
    def __init__(self, parts) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, parts, final: bool = True) -> None:
        self._final = final
        self.content = FakeContent(parts)

    def is_final_response(self) -> bool:
        return self._final


class FakeRunner:
    def __init__(self, events=None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.kwargs = None

    async def run_async(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        for event in self.events:
            yield event


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hello",
    )


def test_run_injects_trace_metadata():
    auditor = FakeAudit()
    runner = FakeRunner([FakeEvent([FakePart("hi")])])
    runtime = AgentRuntime(runner, audit=auditor)

    result = asyncio.run(runtime.run(_invocation(), user_id="u1", session_id="s1"))

    assert result.text == "hi"
    assert result.run_id == "r1"
    assert result.trace_id == "tr1"
    metadata = runner.kwargs["run_config"].custom_metadata
    assert metadata["run_id"] == "r1"
    assert metadata["trace_id"] == "tr1"
    assert metadata["principal"]["subject"] == "alice"
    assert metadata["agent_ref"]["id"] == "support-bot"


def test_run_filters_thought_parts():
    runner = FakeRunner([FakeEvent([FakePart("thinking", thought=True), FakePart("answer")])])
    result = asyncio.run(AgentRuntime(runner).run(_invocation(), user_id="u1", session_id="s1"))
    assert result.text == "answer"


def test_run_is_audited():
    auditor = FakeAudit()
    runner = FakeRunner([FakeEvent([FakePart("hi")])])
    asyncio.run(
        AgentRuntime(runner, audit=auditor).run(_invocation(), user_id="u1", session_id="s1")
    )

    [event] = auditor.events
    assert event.action == "agent.run"
    assert event.target == "support-bot@1.0.0"
    assert event.status == "ok"
    assert event.run_id == "r1"
    assert event.trace_id == "tr1"
    assert event.args_hash
    assert event.result_hash
    assert event.egress == "none"


def test_run_error_is_audited_and_reraised():
    auditor = FakeAudit()
    runner = FakeRunner(error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        asyncio.run(
            AgentRuntime(runner, audit=auditor).run(_invocation(), user_id="u1", session_id="s1")
        )

    [event] = auditor.events
    assert event.status == "error"
    assert event.error_code == "RuntimeError"


def test_run_uses_invocation_input():
    runner = FakeRunner([FakeEvent([FakePart("hi")])])
    asyncio.run(AgentRuntime(runner).run(_invocation(), user_id="u1", session_id="s1"))
    message = runner.kwargs["new_message"]
    assert message.parts[0].text == "hello"
    assert message.role == "user"


def test_run_sets_and_clears_the_invocation():
    from adk_agent.runtime.context import current_invocation

    class _Runner:
        def __init__(self) -> None:
            self.seen = []

        async def run_async(self, **kwargs):
            self.seen.append(current_invocation())
            if False:
                yield

    runner = _Runner()
    runtime = AgentRuntime(runner)
    invocation = _invocation()

    asyncio.run(runtime.run(invocation, user_id="u1", session_id="s1"))

    assert runner.seen == [invocation]
    assert current_invocation() is None
