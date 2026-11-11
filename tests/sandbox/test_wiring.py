"""SLICE-022: the sandbox wraps ADK tool callables and runs inside the loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import helpers
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types

from adk_agent.audit.hashing import safe_hash_json
from adk_agent.core import AgentRef, Invocation, Principal, ToolGrant
from adk_agent.runtime import AgentRuntime
from adk_agent.sandbox import SandboxPolicy, ToolSandbox, install_tool_sandbox, sandboxed_callable
from adk_agent.tools import GrantPolicyEngine
from adk_agent.tools.guard import ToolGuard, install_tool_guard


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class FakeToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        return []


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    turns: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.turns += 1
        if self.turns == 1:
            part = types.Part.from_function_call(name="add", args={"a": 1, "b": 2})
            yield LlmResponse(content=types.Content(role="model", parts=[part]))
        else:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="done")]))


def _sandbox() -> ToolSandbox:
    return ToolSandbox(SandboxPolicy(timeout_seconds=10.0))


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="sandbox-bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )


def test_sandboxed_callable_preserves_name():
    wrapped = sandboxed_callable(helpers.add, _sandbox())
    assert wrapped.__name__ == "add"
    assert asyncio.run(wrapped(a=1, b=2)) == 3


def test_install_tool_sandbox_wraps_callables_and_subagents():
    toolset = FakeToolset()
    sub = LlmAgent(
        name="sub",
        model="gemini-2.5-pro",
        instruction="x",
        tools=[helpers.add],
    )
    parent = LlmAgent(
        name="parent",
        model="gemini-2.5-pro",
        instruction="x",
        tools=[helpers.add, toolset],
        sub_agents=[sub],
    )

    install_tool_sandbox(parent, _sandbox())

    assert getattr(parent.tools[0], "__sandboxed__", False) is True
    assert parent.tools[1] is toolset
    assert getattr(sub.tools[0], "__sandboxed__", False) is True


def test_install_tool_sandbox_is_idempotent():
    agent = LlmAgent(
        name="agent",
        model="gemini-2.5-pro",
        instruction="x",
        tools=[helpers.add],
    )
    sandbox = _sandbox()
    install_tool_sandbox(agent, sandbox)
    first = agent.tools[0]
    install_tool_sandbox(agent, sandbox)
    assert agent.tools[0] is first


def test_agent_tool_call_runs_in_sandbox():
    async def scenario() -> FakeAudit:
        audit = FakeAudit()
        agent = LlmAgent(
            name="a",
            model=ScriptedLlm(),
            instruction="use add",
            tools=[helpers.add],
        )
        install_tool_sandbox(agent, _sandbox())
        install_tool_guard(agent, ToolGuard(GrantPolicyEngine([ToolGrant(tool_id="add")]), audit))

        session_service = InMemorySessionService()
        session = await session_service.create_session(app_name="a", user_id="u")
        runner = Runner(app_name="a", agent=agent, session_service=session_service)
        await AgentRuntime(runner, audit=audit).run(
            _invocation(), user_id="u", session_id=session.id
        )
        return audit

    audit = asyncio.run(scenario())
    tool_events = [event for event in audit.events if event.action == "tool.call"]
    assert len(tool_events) == 1
    assert tool_events[0].status == "ok"
    assert tool_events[0].result_hash == safe_hash_json(3)
