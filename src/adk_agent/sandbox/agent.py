"""Agent-level sandbox capability (ADR-0024). The worker lands in SLICE-129."""

from __future__ import annotations

from ..core import AgentManifest

_backend: object | None = None


class AgentSandboxUnavailable(RuntimeError):
    """A sandboxed manifest was used while no agent sandbox backend is registered."""


def set_agent_sandbox_backend(backend: object | None) -> None:
    """Register the agent sandbox backend; ``None`` means the capability is absent."""
    global _backend
    _backend = backend


def agent_sandbox_backend() -> object | None:
    return _backend


def agent_sandbox_available() -> bool:
    return _backend is not None


def require_execution_supported(manifest: AgentManifest) -> None:
    """Refuse a sandboxed manifest when nothing can run it."""
    if manifest.execution_tier == "sandboxed" and not agent_sandbox_available():
        raise AgentSandboxUnavailable("agent sandbox is not available")
