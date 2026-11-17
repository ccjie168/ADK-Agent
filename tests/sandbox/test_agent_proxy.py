"""SLICE-134: the sandbox agent proxy forwards runs to the backend."""

from __future__ import annotations

import asyncio

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from adk_agent.core import AgentArtifact, AgentManifest
from adk_agent.sandbox.agent import SandboxResult
from adk_agent.sandbox.proxy import build_sandbox_agent


class _Backend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str]] = []
        self.invocations: list = []

    async def run(
        self,
        artifact: AgentArtifact,
        data: bytes,
        input_text: str,
        *,
        manifest=None,
        invocation=None,
    ) -> SandboxResult:
        self.calls.append((artifact.digest, data, input_text))
        self.invocations.append(invocation)
        return SandboxResult(text="hello from the sandbox")


def _manifest() -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        description="sandboxed bot",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="sandboxed",
    )


def _artifact() -> AgentArtifact:
    return AgentArtifact(digest="sha256:" + "a" * 64, size=4)


def test_sandbox_agent_runs_backend():
    backend = _Backend()
    agent = build_sandbox_agent(_manifest(), _artifact(), b"zip!", backend)

    async def run() -> list:
        service = InMemorySessionService()
        runner = Runner(app_name="app", agent=agent, session_service=service)
        session = await service.create_session(app_name="app", user_id="local")
        return [
            event
            async for event in runner.run_async(
                user_id="local",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="hi")]),
            )
        ]

    events = asyncio.run(run())

    assert backend.calls == [(_artifact().digest, b"zip!", "hi")]
    texts = [
        part.text
        for event in events
        if event.content is not None
        for part in event.content.parts or []
        if getattr(part, "text", None)
    ]
    assert "hello from the sandbox" in texts


def test_sandbox_agent_keeps_no_state_between_runs():
    backend = _Backend()
    agent = build_sandbox_agent(_manifest(), _artifact(), b"zip!", backend)

    assert asyncio.run(
        agent.backend.run(agent.artifact, agent.data, "one", manifest=agent.manifest)
    ).text
    assert asyncio.run(
        agent.backend.run(agent.artifact, agent.data, "two", manifest=agent.manifest)
    ).text
    assert [call[2] for call in backend.calls] == ["one", "two"]


def test_sandbox_agent_passes_the_current_invocation():
    from adk_agent.core import AgentRef, Invocation, Principal
    from adk_agent.runtime.context import reset_invocation, set_invocation

    backend = _Backend()
    agent = build_sandbox_agent(_manifest(), _artifact(), b"zip!", backend)
    invocation = Invocation(
        run_id="r1",
        trace_id="t1",
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1.0.0", digest="d" * 64),
        input="hi",
    )

    async def run():
        service = InMemorySessionService()
        runner = Runner(app_name="app", agent=agent, session_service=service)
        session = await service.create_session(app_name="app", user_id="local")
        return [
            event
            async for event in runner.run_async(
                user_id="local",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="hi")]),
            )
        ]

    token = set_invocation(invocation)
    try:
        asyncio.run(run())
    finally:
        reset_invocation(token)

    assert backend.invocations == [invocation]
