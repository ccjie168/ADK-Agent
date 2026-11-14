"""Session stores for single-process demos and shared worker fleets (ADR-0005)."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any

from ..core import Principal
from ..core.context import current_invocation

_INSTALL_HINT = (
    "the Postgres session store needs optional drivers; install them with "
    "`pip install 'sqlalchemy[asyncio]>=2' asyncpg`."
)


class SessionStoreUnavailable(RuntimeError):
    """The driver for the configured shared session store is not installed."""


def _import_module(name: str) -> Any:
    """Indirection so tests can simulate a missing optional driver."""
    return importlib.import_module(name)


_TENANT: ContextVar[str | None] = ContextVar("adk_session_tenant", default=None)


def current_session_tenant() -> str | None:
    """The authenticated tenant for the current session call, if any."""
    tenant = _TENANT.get()
    if tenant:
        return tenant
    invocation = current_invocation()
    if invocation is None:
        return None
    return invocation.principal.tenant


@contextmanager
def session_tenant(tenant: str) -> Iterator[None]:
    token: Token[str | None] = _TENANT.set(tenant)
    try:
        yield
    finally:
        _TENANT.reset(token)


def build_session_service(
    *, url: str | None = None, sqlite_path: str | None = None, rls: bool = False
) -> Any:
    """Build a session service. A configured URL wins over the SQLite demo path."""
    if rls and not (url and url.startswith(("postgresql://", "postgresql+asyncpg://"))):
        raise ValueError("session RLS requires a postgresql SESSION_URL")
    if url:
        if url == "memory://":
            from google.adk.sessions import InMemorySessionService

            return InMemorySessionService()
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        if url.startswith("postgresql+asyncpg://"):
            try:
                module = _import_module("google.adk.sessions.database_session_service")
            except ImportError as exc:
                raise SessionStoreUnavailable(_INSTALL_HINT) from exc
            service = module.DatabaseSessionService(url)
            if rls:
                from .session_rls import install_session_rls

                install_session_rls(service.db_engine)
            return service
        raise ValueError(
            "SESSION_URL must be memory:// or a postgresql+asyncpg:// DSN; "
            "use --session-db for the single-node SQLite demo"
        )

    if sqlite_path:
        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        return SqliteSessionService(sqlite_path)

    from google.adk.sessions import InMemorySessionService

    return InMemorySessionService()


def configured_session_service(session_db: str | None, *, rls: bool = False) -> Any | None:
    """Return the configured external store, or ``None`` for ADK's in-memory default."""
    url = os.environ.get("SESSION_URL")
    if url:
        return build_session_service(url=url, rls=rls)
    if session_db:
        return build_session_service(sqlite_path=session_db, rls=rls)
    return None


def scoped_user_id(principal: Principal) -> str:
    return f"{principal.tenant}:{principal.subject}"


__all__ = [
    "SessionStoreUnavailable",
    "build_session_service",
    "configured_session_service",
    "current_session_tenant",
    "scoped_user_id",
    "session_tenant",
]
