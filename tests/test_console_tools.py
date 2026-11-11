"""SLICE-020: the console installs the tool guard."""

from __future__ import annotations

import asyncio
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import BaseTool

from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, Invocation, Principal
from adk_agent.core.context import reset_invocation, set_invocation
from adk_agent.tools.guard import ToolGuard


class FakeContext:
    def __init__(self, function_call_id: str = "call-1") -> None:
        self.function_call_id = function_call_id


class FakeTool(BaseTool):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description="fake tool")


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="probe", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def _agent() -> LlmAgent:
    def get_time() -> str:
        """Return the current time."""
        return "now"

    sub = LlmAgent(name="sub", model="gemini-2.5-pro", instruction="x")
    return LlmAgent(
        name="probe",
        model="gemini-2.5-pro",
        instruction="x",
        tools=[get_time],
        sub_agents=[sub],
    )


def _guard_for(agent: LlmAgent) -> ToolGuard:
    callbacks = agent.before_tool_callback
    assert callbacks
    guard = getattr(callbacks[0], "__self__", None)
    assert isinstance(guard, ToolGuard)
    return guard


def test_console_installs_tool_guard():
    agent = _agent()
    build_console_app({"probe": agent}, auth_token="secret")

    for current in (agent, agent.sub_agents[0]):
        assert isinstance(current.before_tool_callback, list)
        assert isinstance(current.after_tool_callback, list)
        assert isinstance(current.on_tool_error_callback, list)
        for callback in (
            current.before_tool_callback[0],
            current.after_tool_callback[0],
            current.on_tool_error_callback[0],
        ):
            assert isinstance(getattr(callback, "__self__", None), ToolGuard)


def test_console_grants_declared_tools():
    agent = _agent()
    build_console_app({"probe": agent}, auth_token="secret")
    guard = _guard_for(agent)

    async def scenario() -> tuple[bool, dict[str, Any] | None]:
        token = set_invocation(_invocation())
        try:
            allowed = await guard.before(FakeTool("get_time"), {}, FakeContext("call-1"))
            denied = await guard.before(FakeTool("delete"), {}, FakeContext("call-2"))
            return allowed is None, denied
        finally:
            reset_invocation(token)

    allowed, denied = asyncio.run(scenario())
    assert allowed is True
    assert denied is not None
    assert denied["error"] == "tool_denied"
