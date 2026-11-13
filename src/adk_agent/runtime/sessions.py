"""Session stores for single-process demos and shared worker fleets (ADR-0005)."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from ..core import Principal

_INSTALL_HINT = (
    "the Postgres session store needs optional drivers; install them with "
    "`pip install 'sqlalchemy[asyncio]>=2' asyncpg`."
)


class SessionStoreUnavailable(RuntimeError):
    """The driver for the configured shared session store is not installed."""


def _import_module(name: str) -> Any:
    """Indirection so tests can simulate a missing optional driver."""
    return importlib.import_module(name)


def build_session_service(*, url: str | None = None, sqlite_path: str | None = None) -> Any:
    """Build a session service. A configured URL wins over the SQLite demo path."""
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
            return module.DatabaseSessionService(url)
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


def configured_session_service(session_db: str | None) -> Any | None:
    """Return the configured external store, or ``None`` for ADK's in-memory default."""
    url = os.environ.get("SESSION_URL")
    if url:
        return build_session_service(url=url)
    if session_db:
        return build_session_service(sqlite_path=session_db)
    return None


def scoped_user_id(principal: Principal) -> str:
    return f"{principal.tenant}:{principal.subject}"


__all__ = [
    "SessionStoreUnavailable",
    "build_session_service",
    "configured_session_service",
    "scoped_user_id",
]
