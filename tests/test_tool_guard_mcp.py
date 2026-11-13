"""SLICE-079: MCP and A2A runs enforce the tool allowlist."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from adk_agent import cli
from adk_agent.core import Principal, ToolGrant
from adk_agent.runtime.audit_proxy import AuditedRunner, wrap_runner
from adk_agent.tools import GrantPolicyEngine, ToolGuard, install_tool_guard
from adk_agent.tools.enforcement import install_declared_guards


class ScriptedLlm(BaseLlm):
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


def _agent() -> tuple[LlmAgent, list[tuple[int, int]]]:
    called: list[tuple[int, int]] = []

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        called.append((a, b))
        return a + b

    agent = LlmAgent(
        name="bot",
        model=ScriptedLlm(tool_name="add"),
        instruction="use add",
        tools=[add],
    )
    return agent, called


def _run_served(agent: LlmAgent) -> None:
    async def go() -> None:
        service = InMemorySessionService()
        session = await service.create_session(app_name="bot", user_id="u")
        runner = Runner(app_name="bot", agent=agent, session_service=service)
        wrapped = wrap_runner(
            runner,
            agent_name="bot",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            audit=None,
            quota=None,
            quota_policy=None,
            require_context=True,
        )
        message = types.Content(role="user", parts=[types.Part(text="hi")])
        async for _ in wrapped.run_async(user_id="u", session_id=session.id, new_message=message):
            pass

    asyncio.run(go())


def test_declared_tool_runs():
    agent, called = _agent()
    install_declared_guards(agent, None)

    _run_served(agent)

    assert called == [(1, 2)]


def test_undeclared_tool_is_denied():
    agent, called = _agent()
    install_tool_guard(agent, ToolGuard(GrantPolicyEngine([])))

    _run_served(agent)

    assert called == []


def test_manifest_grants_override_declared_tools():
    agent, called = _agent()
    agent._adk_tool_grants = (ToolGrant(tool_id="other"),)
    install_declared_guards(agent, None)

    _run_served(agent)

    assert called == []


def test_require_context_without_audit():
    wrapped = wrap_runner(
        object(),
        agent_name="bot",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        audit=None,
        quota=None,
        quota_policy=None,
        require_context=True,
    )

    assert isinstance(wrapped, AuditedRunner)


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "def ping() -> str:\n"
        "    '''ping.'''\n"
        "    return 'pong'\n"
        "agents = {'bot': LlmAgent(name='bot', model='gemini-2.5-pro', instruction='x', tools=[ping])}\n",
        encoding="utf-8",
    )
    return str(path)


def test_cli_serve_installs_guard(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.mcp.server.serve_agent", lambda *a, **k: captured.update(k))

    cli.main(["serve", "--agent", _agents_file(tmp_path), "--name", "bot"])

    assert captured["tool_guard"] is True
    assert captured["agent"].before_tool_callback


def test_cli_serve_many_installs_guards(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.mcp.server.serve_many", lambda *a, **k: captured.update(k))

    cli.main(["serve-many", "--agents", _agents_file(tmp_path)])

    assert captured["tool_guard"] is True
    assert all(agent.before_tool_callback for agent in captured["agents"].values())


def test_cli_a2a_installs_guard(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.a2a.serve_a2a", lambda *a, **k: captured.update(k))

    cli.main(["serve-a2a", "--agent", _agents_file(tmp_path)])

    assert captured["require_context"] is True
    assert captured["agent"].before_tool_callback
