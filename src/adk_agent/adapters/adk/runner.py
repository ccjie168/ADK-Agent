"""ADK runners: construction, the internal ``_build_runner`` and the audit facade."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from typing import Any

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner

__all__ = ["Runner", "RunnerFacade", "as_runner", "build_runner", "make_runner", "run_config"]

# Attributes ``Runner`` itself declares. ``__getattr__`` never fires for those,
# so the facade delegates them explicitly; writes go to the target as well.
_DELEGATED = frozenset(
    {
        "app",
        "agent",
        "app_name",
        "artifact_service",
        "context_cache_config",
        "credential_service",
        "memory_service",
        "plugin_manager",
        "resumability_config",
        "session_service",
    }
)


def make_runner(*, app_name: str, agent: Any, session_service: Any, **kwargs: Any) -> Runner:
    """Build a real ADK ``Runner`` for one agent."""
    return Runner(app_name=app_name, agent=agent, session_service=session_service, **kwargs)


def build_runner(agent: Any) -> Runner:
    """ADK's own runner factory, used where no session service is configured."""
    from google.adk.tools.mcp_tool import _agent_to_mcp

    return _agent_to_mcp._build_runner(agent)


def run_config(custom_metadata: Mapping[str, Any]) -> RunConfig:
    """A ``RunConfig`` carrying the platform's run metadata."""
    return RunConfig(custom_metadata=dict(custom_metadata))


def as_runner(value: Any) -> Runner:
    """Return ``value`` itself when it is a real ``Runner``, else wrap it."""
    return value if isinstance(value, Runner) else RunnerFacade(value)


class RunnerFacade(Runner):
    """A real ``ADK Runner`` whose behaviour is delegated to ``target``.

    ADK's A2A executor gates the injected runner with ``isinstance(runner,
    Runner)``.  The platform wraps runners in an audit/quota proxy that is not a
    ``Runner``; this facade gives that proxy a genuine ``Runner`` type without
    faking ``__class__``.
    """

    def __init__(self, target: Any) -> None:
        object.__setattr__(self, "_target", target)

    @property
    def target(self) -> Any:
        return object.__getattribute__(self, "_target")

    async def run_async(self, **kwargs: Any) -> AsyncGenerator[Any, None]:
        async for event in self._target.run_async(**kwargs):
            yield event

    def __getattribute__(self, name: str) -> Any:
        if name in _DELEGATED:
            return getattr(object.__getattribute__(self, "_target"), name)
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _DELEGATED:
            setattr(object.__getattribute__(self, "_target"), name, value)
            return
        object.__setattr__(self, name, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_target"), name)
