"""Request-scoped invocation context for model calls."""

from __future__ import annotations

from contextvars import ContextVar, Token

from .invocation import Invocation

_CURRENT: ContextVar[Invocation | None] = ContextVar("adk_agent_invocation", default=None)


def current_invocation() -> Invocation | None:
    return _CURRENT.get()


def set_invocation(invocation: Invocation) -> Token[Invocation | None]:
    return _CURRENT.set(invocation)


def reset_invocation(token: Token[Invocation | None]) -> None:
    _CURRENT.reset(token)
