"""SLICE-020: the ADK tool loop goes through policy and audit."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import BaseTool
from google.genai import types

from adk_agent.core import AgentRef, Invocation, Principal, ToolGrant
from adk_agent.core.context import reset_invocation, set_invocation
from adk_agent.runtime import AgentRuntime
from adk_agent.tools import GrantPolicyEngine, ToolDenied
from adk_agent.tools.guard import ToolGuard, install_tool_guard


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class FakeContext:
    def __init__(self, function_call_id: str = "call-1") -> None:
        self.function_call_id = function_call_id


class FakeTool(BaseTool):
    def __init__(self, name: str = "add", data_classes: list[str] | None = None) -> None:
        metadata = {"data_classes": data_classes} if data_classes is not None else None
        super().__init__(name=name, description="fake tool", custom_metadata=metadata)


class ScriptedLlm(BaseLlm):
    """First turn calls one tool, second turn answers with text."""

    model: str = "scripted"
    tool_name: str = "add"
    turns: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.turns += 1
        if self.turns == 1:
            part = types.Part.from_function_call(name=self.tool_name, args={"a": 1, "b": 2})
            yield LlmResponse(content=types.Content(role="model", parts=[part]))
        else:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="done")]))


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _guard(tool_id: str | None = "add", audit: FakeAudit | None = None) -> ToolGuard:
    grants = [ToolGrant(tool_id=tool_id)] if tool_id else []
    return ToolGuard(GrantPolicyEngine(grants), audit=audit)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_allowed_tool_is_audited():
    async def scenario() -> FakeAudit:
        audit = FakeAudit()
        guard = _guard(audit=audit)
        tool = FakeTool()
        context = FakeContext()
        token = set_invocation(_invocation())
        try:
            assert await guard.before(tool, {"a": 1, "b": 2}, context) is None
            await guard.after(tool, {"a": 1, "b": 2}, context, 3)
        finally:
            reset_invocation(token)
        return audit

    audit = _run(scenario())
    [event] = audit.events
    assert event.action == "tool.call"
    assert event.target == "add"
    assert event.status == "ok"
    assert event.args_hash
    assert event.result_hash
    assert event.latency_ms is not None
    assert event.egress == "none"


def test_denied_tool_is_not_called():
    async def scenario() -> FakeAudit:
        audit = FakeAudit()
        guard = _guard(tool_id=None, audit=audit)
        tool = FakeTool()
        context = FakeContext()
        token = set_invocation(_invocation())
        try:
            response = await guard.before(tool, {"a": 1, "b": 2}, context)
            assert response == {
                "error": "tool_denied",
                "reason": "tool not granted",
                "tool": "add",
            }
            await guard.after(tool, {"a": 1, "b": 2}, context, response)
        finally:
            reset_invocation(token)
        return audit

    audit = _run(scenario())
    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "policy_denied"
    assert event.result_hash is None


def test_tool_call_without_invocation_is_denied():
    guard = _guard()
    with pytest.raises(ToolDenied):
        _run(guard.before(FakeTool(), {}, FakeContext()))


def test_tool_error_is_audited():
    async def scenario() -> FakeAudit:
        audit = FakeAudit()
        guard = _guard(audit=audit)
        tool = FakeTool()
        context = FakeContext()
        token = set_invocation(_invocation())
        try:
            assert await guard.before(tool, {}, context) is None
            await guard.on_error(tool, {}, context, RuntimeError("boom"))
        finally:
            reset_invocation(token)
        return audit

    audit = _run(scenario())
    [event] = audit.events
    assert event.status == "error"
    assert event.error_code == "RuntimeError"


def test_data_classes_from_tool_metadata():
    async def scenario() -> FakeAudit:
        audit = FakeAudit()
        guard = _guard(audit=audit)
        tool = FakeTool(data_classes=["internal"])
        context = FakeContext()
        token = set_invocation(_invocation())
        try:
            await guard.before(tool, {}, context)
            await guard.after(tool, {}, context, "ok")
        finally:
            reset_invocation(token)
        return audit

    audit = _run(scenario())
    [event] = audit.events
    assert event.data_classes == ["internal"]


def test_install_guard_prepends_and_covers_subagents():
    async def existing_before(tool: BaseTool, args: dict, context: Any) -> None:
        return None

    guard = _guard()
    sub = LlmAgent(name="sub", model="gemini-2.5-flash", instruction="x")
    parent = LlmAgent(
        name="parent",
        model="gemini-2.5-flash",
        instruction="x",
        sub_agents=[sub],
        before_tool_callback=existing_before,
    )

    install_tool_guard(parent, guard)

    assert parent.before_tool_callback == [guard.before, existing_before]
    assert parent.after_tool_callback == [guard.after]
    assert parent.on_tool_error_callback == [guard.on_error]
    assert sub.before_tool_callback == [guard.before]
    assert sub.after_tool_callback == [guard.after]
    assert sub.on_tool_error_callback == [guard.on_error]


def test_agent_tool_call_is_guarded():
    async def scenario() -> tuple[list[tuple[int, int]], FakeAudit]:
        called: list[tuple[int, int]] = []

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            called.append((a, b))
            return a + b

        audit = FakeAudit()
        agent = LlmAgent(
            name="a",
            model=ScriptedLlm(tool_name="add"),
            instruction="use add",
            tools=[add],
        )
        install_tool_guard(agent, _guard(audit=audit))

        session_service = InMemorySessionService()
        session = await session_service.create_session(app_name="a", user_id="u")
        runner = Runner(app_name="a", agent=agent, session_service=session_service)
        runtime = AgentRuntime(runner, audit=audit)
        await runtime.run(_invocation(), user_id="u", session_id=session.id)
        return called, audit

    called, audit = _run(scenario())
    assert called == [(1, 2)]
    tool_events = [event for event in audit.events if event.action == "tool.call"]
    assert len(tool_events) == 1
    assert tool_events[0].status == "ok"
    assert tool_events[0].target == "add"


def test_agent_denied_tool_is_not_executed():
    async def scenario() -> tuple[list[tuple[int, int]], FakeAudit]:
        called: list[tuple[int, int]] = []

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            called.append((a, b))
            return a + b

        audit = FakeAudit()
        agent = LlmAgent(
            name="a",
            model=ScriptedLlm(tool_name="add"),
            instruction="use add",
            tools=[add],
        )
        install_tool_guard(agent, _guard(tool_id=None, audit=audit))

        session_service = InMemorySessionService()
        session = await session_service.create_session(app_name="a", user_id="u")
        runner = Runner(app_name="a", agent=agent, session_service=session_service)
        runtime = AgentRuntime(runner, audit=audit)
        await runtime.run(_invocation(), user_id="u", session_id=session.id)
        return called, audit

    called, audit = _run(scenario())
    assert called == []
    tool_events = [event for event in audit.events if event.action == "tool.call"]
    assert len(tool_events) == 1
    assert tool_events[0].status == "denied"
    assert tool_events[0].error_code == "policy_denied"
