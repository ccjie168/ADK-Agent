"""The invocation a run is currently serving (ADR-0024)."""

from __future__ import annotations

from contextvars import ContextVar, Token

from ..core import Invocation

_current: ContextVar[Invocation | None] = ContextVar("adk_current_invocation", default=None)


def current_invocation() -> Invocation | None:
    return _current.get()


def set_invocation(invocation: Invocation) -> Token[Invocation | None]:
    return _current.set(invocation)


def reset_invocation(token: Token[Invocation | None]) -> None:
    _current.reset(token)


__all__ = ["current_invocation", "reset_invocation", "set_invocation"]
