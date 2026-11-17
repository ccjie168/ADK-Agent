"""Agent-level sandbox capability (ADR-0024)."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..core import AgentArtifact, AgentManifest


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandboxed run."""

    text: str
    limits: Mapping[str, int] = field(default_factory=dict)


class AgentSandboxUnavailable(RuntimeError):
    """A sandboxed manifest was used while no agent sandbox backend is registered."""


@runtime_checkable
class AgentSandboxBackend(Protocol):
    """Execution seam for sandboxed artifacts."""

    async def run(self, artifact: AgentArtifact, data: bytes, input_text: str) -> SandboxResult: ...


_backend: AgentSandboxBackend | None = None


def set_agent_sandbox_backend(backend: AgentSandboxBackend | None) -> None:
    """Register the agent sandbox backend; ``None`` means the capability is absent."""
    if backend is not None:
        run = getattr(backend, "run", None)
        if not callable(run) or not inspect.iscoroutinefunction(run):
            raise TypeError("agent sandbox backend must implement an async run()")
    global _backend
    _backend = backend


def agent_sandbox_backend() -> AgentSandboxBackend | None:
    return _backend


def agent_sandbox_available() -> bool:
    return _backend is not None


def require_execution_supported(manifest: AgentManifest) -> None:
    """Refuse a sandboxed manifest when nothing can run it."""
    if manifest.execution_tier == "sandboxed" and not agent_sandbox_available():
        raise AgentSandboxUnavailable("agent sandbox is not available")
