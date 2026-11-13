"""SLICE-080: approved temporary grants feed the tool policy."""

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
from google.genai import types

from adk_agent import cli
from adk_agent.core import AgentRef, GrantStoreUnavailable, Invocation, Principal, ToolGrant
from adk_agent.core.context import reset_invocation, set_invocation
from adk_agent.registry import FileToolGrantStore
from adk_agent.runtime.audit_proxy import wrap_runner
from adk_agent.tools import GrantPolicyEngine, ToolGuard
from adk_agent.tools.enforcement import install_declared_guards

DIGEST = "sha256:" + "a" * 64


class FakeOverlay:
    def __init__(self, *, active: bool = True, error: Exception | None = None) -> None:
        self.active_result = active
        self.error = error
        self.calls: list[tuple] = []

    async def active(self, tenant, agent_id, version, digest, tool_id, now=None):
        self.calls.append((tenant, agent_id, version, digest, tool_id))
        if self.error is not None:
            raise self.error
        return self.active_result


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


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


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1.0.0", digest=DIGEST),
        input="hi",
    )


def _decision(engine: GrantPolicyEngine):
    return asyncio.run(engine.decide(_invocation(), "tool.call", "crm.read"))


def test_manifest_grant_wins():
    overlay = FakeOverlay(active=False)
    engine = GrantPolicyEngine([ToolGrant(tool_id="crm.read")], overlay=overlay)

    decision = _decision(engine)

    assert decision.decision == "allow"
    assert overlay.calls == []


def test_overlay_grant_allows():
    overlay = FakeOverlay(active=True)
    engine = GrantPolicyEngine([], overlay=overlay)

    decision = _decision(engine)

    assert decision.decision == "allow"
    assert decision.policy_version == "grants-v2"
    assert overlay.calls == [("t1", "bot", "1.0.0", DIGEST, "crm.read")]


def test_overlay_miss_denies():
    engine = GrantPolicyEngine([], overlay=FakeOverlay(active=False))

    assert _decision(engine).decision == "deny"


def test_store_error_denies():
    audit = FakeAudit()
    engine = GrantPolicyEngine([], overlay=FakeOverlay(error=GrantStoreUnavailable("down")))
    guard = ToolGuard(engine, audit=audit)

    class Tool:
        name = "crm.read"

    class Context:
        function_call_id = "call-1"

    token = set_invocation(_invocation())
    try:
        response = asyncio.run(guard.before(Tool(), {}, Context()))
    finally:
        reset_invocation(token)

    assert response["error"] == "tool_denied"
    [event] = audit.events
    assert event.status == "denied"
    assert event.error_code == "grant_store_unavailable"


def test_overlay_allows_through_runner():
    called: list[tuple[int, int]] = []

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        called.append((a, b))
        return a + b

    agent = LlmAgent(name="bot", model=ScriptedLlm(), instruction="use add", tools=[add])
    agent._adk_tool_grants = ()
    install_declared_guards(agent, None, overlay=FakeOverlay(active=True))

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

    assert called == [(1, 2)]


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "def ping() -> str:\n"
        "    '''ping.'''\n"
        "    return 'pong'\n"
        "bot = LlmAgent(name='bot', model='gemini-2.5-pro', instruction='x', tools=[ping])\n"
        "agent = bot\n"
        "agents = {'bot': bot}\n",
        encoding="utf-8",
    )
    return str(path)


def test_console_wires_grant_store(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(
        [
            "console",
            "--agents",
            _agents_file(tmp_path),
            "--tool-grants-dir",
            str(tmp_path / "grants"),
        ]
    )

    assert isinstance(captured["tool_grants"], FileToolGrantStore)


def test_serve_wires_grant_store(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.mcp.server.serve_agent", lambda *a, **k: captured.update(k))
    monkeypatch.setattr(
        "adk_agent.tools.install_declared_guards",
        lambda agent, audit, overlay=None: captured.update(overlay=overlay),
    )

    cli.main(
        [
            "serve",
            "--agent",
            _agents_file(tmp_path),
            "--tool-grants-dir",
            str(tmp_path / "grants"),
        ]
    )

    assert isinstance(captured["overlay"], FileToolGrantStore)


def test_grant_url_builds_postgres_store(tmp_path, monkeypatch):
    created: list = []

    class FakeStore:
        def __init__(self, url: str) -> None:
            created.append(url)

    monkeypatch.setenv(
        "GRANT_URL",
        "postgresql://adk:adk@127.0.0.1:55432/adk",  # pragma: allowlist secret
    )
    monkeypatch.setattr("adk_agent.registry.PostgresToolGrantStore", FakeStore)
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(["console", "--agents", _agents_file(tmp_path)])

    assert isinstance(captured["tool_grants"], FakeStore)
    assert created == [
        "postgresql://adk:adk@127.0.0.1:55432/adk"  # pragma: allowlist secret
    ]


def test_grant_source_exclusive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(
        "GRANT_URL",
        "postgresql://adk:adk@127.0.0.1:55432/adk",  # pragma: allowlist secret
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                _agents_file(tmp_path),
                "--tool-grants-dir",
                str(tmp_path / "grants"),
            ]
        )

    assert exc.value.code == 1
    assert "grant" in capsys.readouterr().err.lower()
