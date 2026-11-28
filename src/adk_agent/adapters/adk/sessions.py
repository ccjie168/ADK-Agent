"""ADK session services the platform can build (ADR-0005)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["database_session_service", "in_memory_session_service", "sqlite_session_service"]


def in_memory_session_service() -> Any:
    from google.adk.sessions import InMemorySessionService

    return InMemorySessionService()


def sqlite_session_service(path: str) -> Any:
    from google.adk.sessions.sqlite_session_service import SqliteSessionService

    return SqliteSessionService(path)


def database_session_service(url: str, *, importer: Callable[[str], Any]) -> Any:
    """Build the Postgres-backed service.

    ``importer`` is the caller's ``importlib.import_module`` indirection, so the
    missing-driver error surfaces where the platform owns the install hint.
    """
    module = importer("google.adk.sessions.database_session_service")
    return module.DatabaseSessionService(url)
