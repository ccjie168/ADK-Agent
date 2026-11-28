"""Sandbox-backed ADK agent (ADR-0024)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from google.genai import types

from ..adapters.adk.agents import BaseAgent, InvocationContext
from ..adapters.adk.events import Event
from ..core import AgentArtifact, AgentManifest
from .agent import AgentSandboxBackend, SandboxResult


def _user_text(ctx: InvocationContext) -> str:
    content = getattr(ctx, "user_content", None)
    for part in getattr(content, "parts", None) or ():
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            return text
    return ""


class SandboxAgent(BaseAgent):
    """Forward each invocation to the sandbox backend and return its text.

    The artifact bytes are never executed in this process. Each invocation
    starts a fresh worker, so the proxy keeps no state between runs.
    """

    artifact: AgentArtifact
    data: bytes
    backend: Any
    manifest: AgentManifest

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from ..core.context import current_invocation

        result: SandboxResult = await self.backend.run(
            self.artifact,
            self.data,
            _user_text(ctx),
            manifest=self.manifest,
            invocation=current_invocation(),
        )
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(text=result.text)]),
        )


def build_sandbox_agent(
    manifest: AgentManifest,
    artifact: AgentArtifact,
    data: bytes,
    backend: AgentSandboxBackend,
) -> SandboxAgent:
    return SandboxAgent(
        name=manifest.id,
        description=manifest.description or "",
        artifact=artifact,
        data=data,
        backend=backend,
        manifest=manifest,
    )


__all__ = ["SandboxAgent", "build_sandbox_agent"]
